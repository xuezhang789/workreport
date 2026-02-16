from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, StreamingHttpResponse, JsonResponse
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.db.models import Q, Count, F
import json

from work_logs.models import DailyReport
from audit.models import AuditLog
from tasks.models import Task
from projects.models import Project
from core.models import Profile

from core.utils import _stream_csv, _create_export_job, _generate_export_file, _admin_forbidden
from core.permissions import has_manage_permission
from reports.utils import get_accessible_projects, get_accessible_reports
from audit.utils import log_action
from reports.services.stats import get_performance_stats as _performance_stats
from reports.daily_report_views import _filtered_reports

MAX_EXPORT_ROWS = 5000
EXPORT_CHUNK_SIZE = 500

@login_required
def my_reports_export(request):
    start_date = parse_date(request.GET.get('start_date') or '')
    end_date = parse_date(request.GET.get('end_date') or '')
    status = (request.GET.get('status') or '').strip()
    project_id = request.GET.get('project')
    role = (request.GET.get('role') or '').strip()
    q = (request.GET.get('q') or '').strip()

    qs = DailyReport.objects.filter(user=request.user).select_related('user').prefetch_related('projects').order_by('-date', '-created_at')
    if start_date:
        qs = qs.filter(date__gte=start_date)
    if end_date:
        qs = qs.filter(date__lte=end_date)
    if status in dict(DailyReport.STATUS_CHOICES):
        qs = qs.filter(status=status)
    if project_id and project_id.isdigit():
        qs = qs.filter(projects__id=int(project_id))
    if role in dict(DailyReport.ROLE_CHOICES):
        qs = qs.filter(role=role)
    if q:
        qs = qs.filter(
            Q(today_work__icontains=q) |
            Q(progress_issues__icontains=q) |
            Q(tomorrow_plan__icontains=q) |
            Q(testing_scope__icontains=q) |
            Q(testing_progress__icontains=q) |
            Q(bug_summary__icontains=q) |
            Q(testing_tomorrow__icontains=q) |
            Q(product_today__icontains=q) |
            Q(product_coordination__icontains=q) |
            Q(product_tomorrow__icontains=q) |
            Q(ui_today__icontains=q) |
            Q(ui_feedback__icontains=q) |
            Q(ui_tomorrow__icontains=q) |
            Q(ops_today__icontains=q) |
            Q(ops_monitoring__icontains=q) |
            Q(ops_tomorrow__icontains=q) |
            Q(mgr_progress__icontains=q) |
            Q(mgr_risks__icontains=q) |
            Q(mgr_tomorrow__icontains=q)
        )
    if qs.count() > MAX_EXPORT_ROWS:
        return HttpResponse("数据量过大，请缩小筛选范围后再导出 / Data too large, please narrow filters.", status=400)

    rows = (
        [
            r.date.isoformat(),
            r.get_role_display(),
            r.get_status_display(),
            r.project_names,
            (r.summary or '')[:200].replace('\n', ' '),
            timezone.localtime(r.created_at).strftime("%Y-%m-%d %H:%M"),
        ]
        for r in qs.iterator(chunk_size=EXPORT_CHUNK_SIZE)
    )
    header = ["日期", "角色", "状态", "项目", "摘要", "创建时间"]
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="my_reports.csv"'
    log_action(request, 'export', f"my_reports count={qs.count()} q={q}")
    return response


@login_required
def admin_reports_export(request):
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)

    reports, role, start_date, end_date = _filtered_reports(request)
    
    # Security Fix: Filter by accessible projects for non-superusers
    if not request.user.is_superuser:
        accessible_projects = get_accessible_projects(request.user)
        reports = reports.filter(projects__in=accessible_projects).distinct()

    if not start_date or not end_date:
        return HttpResponse("请提供开始和结束日期后再导出。", status=400)

    username = (request.GET.get('username') or '').strip()
    project_id = request.GET.get('project')
    status = (request.GET.get('status') or '').strip()
    if username:
        reports = reports.filter(
            Q(user__username__icontains=username) |
            Q(user__first_name__icontains=username) |
            Q(user__last_name__icontains=username)
        )
    if project_id and project_id.isdigit():
        reports = reports.filter(projects__id=int(project_id))
    if status in dict(DailyReport.STATUS_CHOICES):
        reports = reports.filter(status=status)

    if not (username or project_id):
        return HttpResponse("请至少指定用户名或项目过滤后再导出。", status=400)

    total_count = reports.count()
    if total_count > MAX_EXPORT_ROWS:
        if request.GET.get('queue') != '1':
            return HttpResponse("数据量过大，请缩小筛选范围后再导出 / Data too large, please narrow filters. 如需排队导出，请带 queue=1 参数 / Use queue=1 to enqueue export.", status=400)
        job = _create_export_job(request.user, 'admin_reports_filtered')
        try:
            _generate_export_file(
                job,
                ["日期", "角色", "项目", "用户", "状态", "摘要", "创建时间"],
                (
                    [
                        str(r.date),
                        r.get_role_display(),
                        r.project_names or "",
                        r.user.get_full_name() or r.user.username,
                        r.get_status_display(),
                        r.summary or "",
                        timezone.localtime(r.created_at).strftime("%Y-%m-%d %H:%M"),
                    ]
                    for r in reports.iterator(chunk_size=EXPORT_CHUNK_SIZE)
                )
            )
            return JsonResponse({'queued': True, 'job_id': job.id})
        except Exception as e:
            job.status = 'failed'
            job.message = str(e)
            job.save(update_fields=['status', 'message', 'updated_at'])
            return JsonResponse({'error': 'export failed'}, status=500)

    rows = (
        [
            str(r.date),
            r.get_role_display(),
            r.project_names or "",
            r.user.get_full_name() or r.user.username,
            r.get_status_display(),
            r.summary or "",
            timezone.localtime(r.created_at).strftime("%Y-%m-%d %H:%M"),
        ]
        for r in reports.iterator(chunk_size=EXPORT_CHUNK_SIZE)
    )
    header = ["日期", "角色", "项目", "作者", "状态", "摘要", "创建时间"]
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="daily_reports.csv"'
    log_action(request, 'export', f"daily_reports count={reports.count()} role={role} start={start_date} end={end_date} username={username} project={project_id}")
    return response


@login_required
def stats_export(request):
    """导出统计相关数据：type=missing|project_sla|user_sla"""
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)

    export_type = (request.GET.get('type') or 'missing').strip()
    target_date = parse_date(request.GET.get('date') or '') or timezone.localdate()
    
    # Security Fix: Filter projects
    projects_qs = Project.objects.filter(is_active=True)
    if not request.user.is_superuser:
        accessible_projects = get_accessible_projects(request.user)
        projects_qs = projects_qs.filter(id__in=accessible_projects).distinct()

    if export_type == 'project_sla':
        tasks_qs = Task.objects.select_related('project')
        # Filter tasks by accessible projects
        if not request.user.is_superuser:
            tasks_qs = tasks_qs.filter(project__in=projects_qs)
            
        projects = projects_qs.order_by('name')
        rows = []
        for p in projects:
            total = tasks_qs.filter(project=p).count()
            completed = tasks_qs.filter(project=p, status='completed').count()
            overdue = tasks_qs.filter(project=p, status='overdue').count()
            within_sla = tasks_qs.filter(
                project=p,
                status='completed',
                due_at__isnull=False,
                completed_at__isnull=False,
                completed_at__lte=F('due_at')
            ).count()
            sla_rate = (within_sla / completed * 100) if completed else 0
            rows.append([
                p.name,
                total,
                completed,
                overdue,
                within_sla,
                f"{sla_rate:.1f}%",
            ])
        header = ["项目", "总任务", "已完成", "逾期", "SLA 内完成", "达成率"]
        filename = f"project_sla_{target_date}.csv"

    elif export_type == 'user_sla':
        tasks_qs = Task.objects.select_related('user')
        if not request.user.is_superuser:
            tasks_qs = tasks_qs.filter(project__in=projects_qs)
            
        grouped = tasks_qs.values('user__username', 'user__first_name', 'user__last_name').annotate(
            total=Count('id'),
            completed=Count('id', filter=Q(status='completed')),
            overdue=Count('id', filter=Q(status='overdue')),
        )
        rows = []
        for g in grouped:
            total = g['total']
            completed = g['completed']
            overdue = g['overdue']
            rows.append([
                g['user__username'],
                f"{(g['user__first_name'] or '')} {(g['user__last_name'] or '')}".strip(),
                total,
                completed,
                overdue,
                f"{(completed/total*100):.1f}%" if total else "0%",
                f"{(overdue/total*100):.1f}%" if total else "0%",
            ])
        header = ["用户名", "姓名", "总任务", "已完成", "逾期", "完成率", "逾期率"]
        filename = f"user_sla_{target_date}.csv"

    else:
        # missing
        qs = DailyReport.objects.filter(date=target_date)
        todays_user_ids = set(qs.values_list('user_id', flat=True))
        active_projects = projects_qs.prefetch_related('members', 'managers')
        rows = []
        for p in active_projects:
            expected_users = set(p.members.values_list('id', flat=True)) | set(p.managers.values_list('id', flat=True))
            if p.owner_id:
                expected_users.add(p.owner_id)
            missing_ids = [uid for uid in expected_users if uid not in todays_user_ids]
            if missing_ids:
                users = get_user_model().objects.filter(id__in=missing_ids)
                rows.append([
                    p.name,
                    len(missing_ids),
                    ", ".join([u.get_full_name() or u.username for u in users]),
                ])
        header = ["项目", "缺报人数", "名单"]
        filename = f"missing_reports_{target_date}.csv"

    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename=\"{filename}\"'
    log_action(request, 'export', f"stats_export type={export_type} date={target_date}")
    return response


@login_required
def audit_logs_export(request):
    if not request.user.is_superuser:
        return _admin_forbidden(request)

    start_date = parse_date(request.GET.get('start_date') or '')
    end_date = parse_date(request.GET.get('end_date') or '')
    action = (request.GET.get('action') or '').strip()
    result = (request.GET.get('result') or '').strip()
    user_q = (request.GET.get('user') or '').strip()
    target_type = (request.GET.get('target_type') or '').strip()

    qs = AuditLog.objects.select_related('user').order_by('-created_at')
    if start_date:
        qs = qs.filter(created_at__date__gte=start_date)
    if end_date:
        qs = qs.filter(created_at__date__lte=end_date)
    if action:
        qs = qs.filter(action=action)
    if result:
        qs = qs.filter(result=result)
    if user_q:
        qs = qs.filter(Q(user__username__icontains=user_q) | Q(user__first_name__icontains=user_q) | Q(user__last_name__icontains=user_q))
    if target_type:
        qs = qs.filter(target_type__icontains=target_type)

    if not (start_date and end_date):
        return HttpResponse("请提供开始和结束日期后再导出。", status=400)
    if qs.count() > MAX_EXPORT_ROWS:
        return HttpResponse("数据量过大，请缩小筛选范围后再导出。", status=400)

    rows = (
        [
            log.created_at.astimezone(timezone.get_current_timezone()).strftime("%Y-%m-%d %H:%M:%S"),
            log.operator_name or (log.user.username if log.user else "System"),
            log.get_action_display(),
            log.get_result_display(),
            log.target_type,
            log.target_id,
            log.target_label,
            json.dumps(log.details, ensure_ascii=False) if log.details else "",
            log.ip or "",
            log.summary or "",
        ]
        for log in qs.iterator(chunk_size=EXPORT_CHUNK_SIZE)
    )
    header = ["时间", "操作人", "动作", "结果", "对象类型", "对象ID", "对象名称", "详情", "IP", "摘要"]
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="audit_logs.csv"'
    log_action(request, 'export', f"audit_logs count={qs.count()} action={action}")
    return response


@login_required
def performance_export(request):
    """导出绩效看板数据，scope=project|role|user|streak。"""
    accessible_projects = None
    if request.user.is_superuser:
        pass
    else:
        accessible_projects = get_accessible_projects(request.user)
        if not accessible_projects.exists():
            messages.error(request, "需要管理员权限 / Admin access required")
            return render(request, '403.html', status=403)
            
    scope = (request.GET.get('scope') or 'project').strip()
    start_date = parse_date(request.GET.get('start') or '') or None
    end_date = parse_date(request.GET.get('end') or '') or None
    project_param = request.GET.get('project')
    role_param = (request.GET.get('role') or '').strip()
    q = request.GET.get('q')
    project_filter = int(project_param) if project_param and project_param.isdigit() else None
    role_filter = role_param if role_param in dict(Profile.ROLE_CHOICES) else None
    
    # Security check for project filter
    # 项目过滤器的安全检查
    if project_filter and accessible_projects is not None:
        if not accessible_projects.filter(id=project_filter).exists():
             return _admin_forbidden(request, "没有该项目的访问权限 / No access to this project")

    stats = _performance_stats(
        start_date=start_date, 
        end_date=end_date, 
        project_id=project_filter, 
        role_filter=role_filter, 
        q=q,
        accessible_projects=accessible_projects
    )

    if scope == 'role':
        rows = [
            [
                item['role_label'],
                item['total'],
                item['completed'],
                item['overdue'],
                f"{item['completion_rate']:.1f}%",
                f"{item['overdue_rate']:.1f}%",
                f"{item['sla_on_time_rate']:.1f}%",
                item['lead_time_p50'] if item['lead_time_p50'] is not None else '',
                item['lead_time_avg'] if item['lead_time_avg'] is not None else '',
            ]
            for item in stats['role_stats']
        ]
        header = ["角色 / Role", "任务总数", "完成", "逾期", "完成率", "逾期率", "SLA 准时率", "Lead Time 中位(h)", "Lead Time 平均(h)"]
        filename = "performance_role.csv"
    elif scope == 'user':
        rows = [
            [
                item['user_label'],
                item['total'],
                item['completed'],
                item['overdue'],
                f"{item['completion_rate']:.1f}%",
                f"{item['overdue_rate']:.1f}%",
                f"{item['sla_on_time_rate']:.1f}%",
                item['lead_time_p50'] if item['lead_time_p50'] is not None else '',
                item['lead_time_avg'] if item['lead_time_avg'] is not None else '',
            ]
            for item in stats['user_stats']
        ]
        header = ["用户 / User", "任务总数", "完成", "逾期", "完成率", "逾期率", "SLA 准时率", "Lead Time 中位(h)", "Lead Time 平均(h)"]
        filename = "performance_user.csv"
    elif scope == 'streak':
        rows = [
            [
                item['role_label'],
                item['avg_streak'],
                item['max_streak'],
            ]
            for item in stats['role_streaks']
        ]
        header = ["角色 / Role", "平均连签天数 / Avg streak", "最高连签天数 / Max streak"]
        filename = "performance_streak.csv"
    else:
        rows = [
            [
                item['project'],
                item['total'],
                item['completed'],
                item['overdue'],
                f"{item['completion_rate']:.1f}%",
                f"{item['overdue_rate']:.1f}%",
                f"{item['sla_on_time_rate']:.1f}%",
                item['lead_time_p50'] if item['lead_time_p50'] is not None else '',
                item['lead_time_avg'] if item['lead_time_avg'] is not None else '',
            ]
            for item in stats['project_stats']
        ]
        header = ["项目 / Project", "任务总数", "完成", "逾期", "完成率", "逾期率", "SLA 准时率", "Lead Time 中位(h)", "Lead Time 平均(h)"]
        filename = "performance_project.csv"

    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    log_action(request, 'export', f"performance scope={scope}")
    return response
