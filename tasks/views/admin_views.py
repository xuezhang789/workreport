import json
import logging
from datetime import datetime, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse, Http404
from django.utils.http import url_has_allowed_host_and_scheme
from django.db.models import Q, Count, Avg, F, Subquery, OuterRef
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.core.paginator import Paginator
from django.contrib import messages
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.core.cache import cache
from django.urls import reverse

from projects.models import Project
from tasks.models import Task, TaskAttachment, TaskTemplateVersion
from core.constants import TaskStatus, TaskCategory
from audit.utils import log_action
from audit.models import AuditLog
from core.models import Profile, SystemSetting
from work_logs.models import DailyReport
from core.utils import (
    _admin_forbidden,
    _validate_file,
    _stream_csv,
    _create_export_job,
    _generate_export_file
)
from tasks.services.sla import (
    calculate_sla_info, 
    get_sla_hours, 
    get_sla_thresholds
)
from tasks.services.export import TaskExportService
from tasks.services.task_service import TaskAdminService
from reports.utils import get_accessible_projects, can_manage_project, get_manageable_projects
from reports.signals import _invalidate_stats_cache

logger = logging.getLogger(__name__)

MAX_EXPORT_ROWS = 5000
EXPORT_CHUNK_SIZE = 500

@login_required
def admin_task_list(request):
    context = TaskAdminService.get_admin_task_list_context(request.user, request.GET, request.get_full_path())
    
    if 'error' in context:
        return _admin_forbidden(request, context['error'])
        
    return render(request, 'tasks/admin_task_list.html', context)


@login_required
def admin_task_bulk_action(request):
    manageable_projects = get_manageable_projects(request.user)
    manageable_project_ids = set(manageable_projects.values_list('id', flat=True))
    
    if not manageable_project_ids:
        return _admin_forbidden(request, "需要管理员或项目管理员权限 / Admin or project manager required")
    if request.method != 'POST':
        return _admin_forbidden(request, "仅允许 POST / POST only")
    ids = request.POST.getlist('task_ids')
    action = request.POST.get('action')  # 修正后的参数名称
    redirect_to = request.POST.get('redirect_to')
    if redirect_to and not url_has_allowed_host_and_scheme(url=redirect_to, allowed_hosts={request.get_host()}):
        redirect_to = None
    
    # 过滤上下文用于记录日志
    project_id = request.POST.get('project')
    user_id = request.POST.get('user')

    total_requested = len(ids)
    # Optimization: Select related project to avoid N+1 in AuditLog creation
    tasks = Task.objects.filter(id__in=ids).select_related('project')
    
    # 按可管理项目过滤（也处理超级管理员）
    tasks = tasks.filter(project_id__in=manageable_project_ids)
    
    skipped_perm = max(0, total_requested - tasks.count())
    total_selected = tasks.count()
    updated = 0
    if action == 'complete':
        now = timezone.now()
        audit_batch = []
        ip = request.META.get('REMOTE_ADDR')
        for t in tasks:
            audit_batch.append(AuditLog(
                user=request.user,
                operator_name=request.user.get_full_name(),
                action='update',
                target_type='Task',
                target_id=str(t.id),
                target_label=str(t)[:255],
                details={'diff': {'status': {'old': t.status, 'new': TaskStatus.DONE}}},
                project=t.project,
                task=t,
                ip=ip,
                result='success'
            ))
        AuditLog.objects.bulk_create(audit_batch)
        tasks.update(status=TaskStatus.DONE, completed_at=now)
        
        # Trigger progress update for affected projects
        for pid in tasks.values_list('project_id', flat=True).distinct():
            Project.objects.get(id=pid).update_progress()
            
        updated = total_selected
        log_action(request, 'update', f"admin_task_bulk_complete count={tasks.count()}")
    elif action == 'reopen':
        audit_batch = []
        ip = request.META.get('REMOTE_ADDR')
        for t in tasks:
            audit_batch.append(AuditLog(
                user=request.user,
                operator_name=request.user.get_full_name(),
                action='update',
                target_type='Task',
                target_id=str(t.id),
                target_label=str(t)[:255],
                details={'diff': {'status': {'old': t.status, 'new': TaskStatus.TODO}}},
                project=t.project,
                task=t,
                ip=ip,
                result='success'
            ))
        AuditLog.objects.bulk_create(audit_batch)
        tasks.update(status=TaskStatus.TODO, completed_at=None)
        
        # Trigger progress update for affected projects
        for pid in tasks.values_list('project_id', flat=True).distinct():
            Project.objects.get(id=pid).update_progress()

        updated = total_selected
        log_action(request, 'update', f"admin_task_bulk_reopen count={tasks.count()}")
    elif action == 'update' or action in ('assign', 'change_status'): # 支持独立动作或合并更新
        # 将前端参数映射到后端逻辑
        status_value = (request.POST.get('target_status') or request.POST.get('status_value') or '').strip()
        assign_to = request.POST.get('target_user') or request.POST.get('assign_to')
        due_at_str = (request.POST.get('due_at') or '').strip()
        
        # 如果动作暗示特定更新，确保我们遵守它
        if action == 'assign' and not assign_to:
             messages.warning(request, "未选择目标用户 / No user selected")
             return redirect(redirect_to or 'tasks:admin_task_list')
        if action == 'change_status' and not status_value:
              messages.warning(request, "未选择目标状态 / No status selected")
              return redirect(redirect_to or 'tasks:admin_task_list')
        
        # 强制动作范围以避免意外更新
        if action == 'assign':
            status_value = ''
            due_at_str = ''
        elif action == 'change_status':
            assign_to = None
            due_at_str = ''
 
        parsed_due = None
        if due_at_str:
            try:
                parsed = datetime.fromisoformat(due_at_str)
                parsed_due = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
            except ValueError:
                messages.error(request, "截止时间格式不正确 / Invalid due date format")
                return redirect(redirect_to or 'tasks:admin_task_list')
        valid_status = status_value in dict(Task.STATUS_CHOICES)
        assign_user = None
        if assign_to and assign_to.isdigit():
            assign_user = get_user_model().objects.filter(id=int(assign_to)).first()
        updated = 0
        now = timezone.now()
        for t in tasks:
            update_fields = []
            if valid_status and status_value != t.status:
                t.status = status_value
                if status_value in ('done', 'closed'):
                    t.completed_at = now
                    update_fields.append('completed_at')
                else:
                    if t.completed_at:
                        t.completed_at = None
                        update_fields.append('completed_at')
                update_fields.append('status')
            if parsed_due and (t.due_at != parsed_due):
                t.due_at = parsed_due
                update_fields.append('due_at')
            if assign_user and assign_user.id != t.user_id:
                t.user = assign_user
                update_fields.append('user')
            if update_fields:
                t.save(update_fields=update_fields)
                updated += 1
        if updated:
            # log_action 已移除，避免与最终摘要日志重复
            pass
    if updated:
        messages.success(request, f"批量操作完成：更新 {updated}/{total_selected} 条")
        if skipped_perm:
            messages.warning(request, f"{skipped_perm} 条因无权限未处理")
        elif total_selected and updated < total_selected:
            messages.warning(request, f"{total_selected - updated} 条未更新，可能因缺少字段或权限限制")
    else:
        messages.info(request, "未更新任何任务，请检查操作与选择")
    log_action(
        request,
        'update',
        f"admin_task_bulk_action {action or '-'} updated={updated} total={total_selected} skipped_perm={skipped_perm}",
        data={
            'action': action,
            'updated': updated,
            'total': total_selected,
            'skipped_perm': skipped_perm,
            'project_filter': project_id,
            'user_filter': user_id,
        },
    )
    _invalidate_stats_cache()
    return redirect(redirect_to or 'tasks:admin_task_list')


@login_required
def admin_task_export(request):
    manageable_projects = get_manageable_projects(request.user)
    manageable_project_ids = set(manageable_projects.values_list('id', flat=True))
    
    if not manageable_project_ids:
        return _admin_forbidden(request, "需要管理员或项目管理员权限 / Admin or project manager required")

    status = (request.GET.get('status') or '').strip()
    priority = (request.GET.get('priority') or '').strip()
    project_id = request.GET.get('project')
    user_id = request.GET.get('user')
    q = (request.GET.get('q') or '').strip()
    hot = request.GET.get('hot') == '1'
    sort_by = request.GET.get('sort', '-created_at')

    tasks = Task.objects.select_related('project', 'user', 'sla_timer').prefetch_related('collaborators')
    
    # 预取一次 SLA 设置
    cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
    sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
    
    cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
    sla_thresholds_val = cfg_thresholds.value if cfg_thresholds else None
    
    tasks = tasks.filter(project_id__in=manageable_project_ids)

    if status in dict(Task.STATUS_CHOICES):
        tasks = tasks.filter(status=status)
    if priority in dict(Task.PRIORITY_CHOICES):
        tasks = tasks.filter(priority=priority)
    if project_id and project_id.isdigit():
        pid = int(project_id)
        if pid in manageable_project_ids:
            tasks = tasks.filter(project_id=pid)
        else:
            tasks = tasks.none()
    if user_id and user_id.isdigit():
        tasks = tasks.filter(user_id=int(user_id))
    if q:
        tasks = tasks.filter(Q(title__icontains=q) | Q(content__icontains=q))

    if not hot:
        allowed_sorts = {
            'created_at': 'created_at',
            '-created_at': '-created_at',
            'priority': 'priority',
            '-priority': '-priority',
            'status': 'status',
            '-status': '-status',
            'due_at': 'due_at',
            '-due_at': '-due_at',
            'title': 'title',
            '-title': '-title',
        }
        sort_field = allowed_sorts.get(sort_by, '-created_at')
        tasks = tasks.order_by(sort_field)
    else:
        # 热门模式默认排序
        tasks = tasks.order_by('-created_at')

    if hot:
        filtered = []
        for t in tasks: # Use default iteration to support prefetch_related
            info = calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)
            if info['status'] in ('tight', 'overdue'):
                t.sla_info = info
                filtered.append(t)
        tasks = filtered

    total_count = len(tasks) if isinstance(tasks, list) else tasks.count()
    if total_count > MAX_EXPORT_ROWS:
        if request.GET.get('queue') != '1':
            return HttpResponse("数据量过大，请缩小筛选范围后再导出 / Data too large, please narrow filters. 如需排队导出，请带 queue=1 参数 / Use queue=1 to enqueue export.", status=400)
        
        job = _create_export_job(request.user, 'admin_tasks')
        try:
            # For background job, we might still want iterator to save memory, 
            # but we need to handle N+1. For now, since it's background, standard iteration is safer for correctness.
            path = _generate_export_file(
                job,
                TaskExportService.get_header(),
                TaskExportService.get_export_rows(tasks)
            )
            return JsonResponse({'queued': True, 'job_id': job.id})
        except Exception as e:
            job.status = 'failed'
            job.message = str(e)
            job.save(update_fields=['status', 'message', 'updated_at'])
            return JsonResponse({'error': 'export failed'}, status=500)

    # 安全/性能修复：移除 iterator() 以允许 prefetch_related 工作
    rows = TaskExportService.get_export_rows(tasks)
    header = TaskExportService.get_header()
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename=\"tasks_admin.csv\"'
    log_action(request, 'export', f"tasks_admin count={total_count} q={q}")
    return response


@login_required
def sla_settings(request):
    if not request.user.is_superuser:
        return _admin_forbidden(request)
    current = get_sla_hours()
    thresholds = get_sla_thresholds()
    if request.method == 'POST':
        hours_str = (request.POST.get('sla_hours') or '').strip()
        amber_str = (request.POST.get('sla_amber') or '').strip()
        red_str = (request.POST.get('sla_red') or '').strip()
        try:
            hours = int(hours_str)
            amber = int(amber_str)
            red = int(red_str)
            if hours < 1 or amber < 1 or red < 1:
                raise ValueError("必须大于 0")
        except (ValueError, TypeError):
            messages.error(request, "请输入有效的小时数（正整数）")
        else:
            SystemSetting.objects.update_or_create(key='sla_hours', defaults={'value': str(hours)})
            SystemSetting.objects.update_or_create(key='sla_thresholds', defaults={'value': json.dumps({'amber': amber, 'red': red})})
            messages.success(request, "SLA 提醒窗口与阈值已保存")
            log_action(request, 'update', f"sla_settings update hours={hours} amber={amber} red={red}")
            current = hours
            thresholds = {'amber': amber, 'red': red}
    return render(request, 'tasks/sla_settings.html', {
        'sla_hours': current,
        'sla_amber': thresholds.get('amber'),
        'sla_red': thresholds.get('red'),
    })


@login_required
def admin_task_stats(request):
    """
    重构后的管理后台任务统计视图 (科学且具有洞察力):
    - 多维度指标 (总量, 完成情况, 效率, 质量).
    - 比较分析 (增长率).
    - 基于时间窗口的过滤 (今天, 本周, 本月).
    """
    User = get_user_model()
    accessible_projects = get_accessible_projects(request.user)
    if not accessible_projects.exists():
        return _admin_forbidden(request, "需要相关项目权限 / Project access required")

    # --- 1. 过滤上下文和日期范围 ---
    period = request.GET.get('period', 'month') # 默认: 本月
    
    # 自定义范围覆盖期间
    custom_start = request.GET.get('start')
    custom_end = request.GET.get('end')
    
    today = timezone.localdate()
    start_date = None
    end_date = None
    prev_start_date = None
    prev_end_date = None
    
    if custom_start or custom_end:
        period = 'custom'
        start_date = parse_date(custom_start) if custom_start else None
        end_date = parse_date(custom_end) if custom_end else None
    else:
        if period == 'today':
            start_date = end_date = today
            prev_start_date = prev_end_date = today - timedelta(days=1)
        elif period == 'week': # 本周 (周一 - 今天)
            start_date = today - timedelta(days=today.weekday())
            end_date = today
            prev_start_date = start_date - timedelta(days=7)
            prev_end_date = end_date - timedelta(days=7)
        elif period == 'month': # 本月 (1号 - 今天)
            start_date = today.replace(day=1)
            end_date = today
            # 上个月
            last_month_end = start_date - timedelta(days=1)
            prev_start_date = last_month_end.replace(day=1)
            prev_end_date = last_month_end # 比较完整的上个月? 或者相同天数? 
            # 通常 "月至今" 比较的是 "上月至今" 或 "完整的上个月"
            # 为了简单起见，比较完整的上个月或相同的持续时间。
            # 这里简单使用: 上个月1号到上个月底。
        elif period == 'year':
            start_date = today.replace(month=1, day=1)
            end_date = today
            prev_start_date = start_date.replace(year=start_date.year - 1)
            prev_end_date = end_date.replace(year=end_date.year - 1)

    # --- 2. 基础查询集 ---
    # 我们需要分离的查询集用于 "创建", "完成", "活跃"
    base_tasks = Task.objects.all()
    base_reports = DailyReport.objects.all()
    
    base_tasks = base_tasks.filter(project__in=accessible_projects)
    base_reports = base_reports.filter(projects__in=accessible_projects)

    # 应用非日期过滤器
    project_id = request.GET.get('project')
    user_id = request.GET.get('user')
    role = request.GET.get('role')
    q = (request.GET.get('q') or '').strip()

    if project_id and project_id.isdigit():
        pid = int(project_id)
        if accessible_projects.filter(id=pid).exists():
            base_tasks = base_tasks.filter(project_id=pid)
            base_reports = base_reports.filter(projects__id=pid)
    
    if user_id and user_id.isdigit():
        uid = int(user_id)
        base_tasks = base_tasks.filter(user_id=uid)
        base_reports = base_reports.filter(user_id=uid)
        
    if q:
        user_q = Q(user__username__icontains=q) | Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
        base_tasks = base_tasks.filter(user_q)
        base_reports = base_reports.filter(user_q)

    if role:
        base_tasks = base_tasks.filter(user__profile__position=role)
        base_reports = base_reports.filter(role=role)

    # --- 3. KPI 计算 (Optimized) ---
    # Optimization: Use single aggregate query for all metrics instead of multiple count() queries
    
    # Cache key for statistics
    cache_key = f"admin_task_stats_data_v3_{request.user.id}_{period}_{start_date}_{end_date}_{project_id}_{user_id}_{role}_{q}"
    stats_data = cache.get(cache_key)
    
    if stats_data is None:
        # 3.1 Construct Aggregation
        aggs = {}
        
        # New Tasks (Current)
        new_q = Q(created_at__date__range=(start_date, end_date)) if (start_date and end_date) else Q()
        aggs['new'] = Count('pk', filter=new_q)
        
        # Done Tasks (Current)
        done_q = Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])
        if start_date and end_date:
            done_q &= Q(completed_at__date__range=(start_date, end_date))
        aggs['done'] = Count('pk', filter=done_q)
        
        # Overdue (Snapshot - Current)
        now = timezone.now()
        overdue_q = Q(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW], due_at__lt=now)
        aggs['overdue'] = Count('pk', filter=overdue_q)
        
        # On Time (Current)
        # Done & Has Due & Completed <= Due
        with_due_q = done_q & Q(due_at__isnull=False)
        on_time_q = with_due_q & Q(completed_at__lte=F('due_at'))
        
        aggs['on_time'] = Count('pk', filter=on_time_q)
        aggs['with_due'] = Count('pk', filter=with_due_q)
        
        # Avg Duration (Current)
        aggs['avg_dur'] = Avg(F('completed_at') - F('created_at'), filter=done_q)
    
        # Previous Period Metrics
        if prev_start_date:
            # Prev New
            prev_new_q = Q(created_at__date__range=(prev_start_date, prev_end_date))
            aggs['prev_new'] = Count('pk', filter=prev_new_q)
            
            # Prev Done
            prev_done_q = Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED], completed_at__date__range=(prev_start_date, prev_end_date))
            aggs['prev_done'] = Count('pk', filter=prev_done_q)
            
            # Prev On Time
            prev_with_due_q = prev_done_q & Q(due_at__isnull=False)
            prev_on_time_q = prev_with_due_q & Q(completed_at__lte=F('due_at'))
            
            aggs['prev_on_time'] = Count('pk', filter=prev_on_time_q)
            aggs['prev_with_due'] = Count('pk', filter=prev_with_due_q)
            
            # Prev Avg Duration
            aggs['prev_avg_dur'] = Avg(F('completed_at') - F('created_at'), filter=prev_done_q)
    
        # Execute Aggregation
        results = base_tasks.aggregate(**aggs)
    
        # 3.2 Extract Results
        metric_new = results.get('new', 0)
        metric_done = results.get('done', 0)
        metric_overdue = results.get('overdue', 0)
        metric_on_time = results.get('on_time', 0)
        tasks_with_due_in_period = results.get('with_due', 0)
        
        avg_dur = results.get('avg_dur')
        metric_avg_time = avg_dur.total_seconds() / 3600 if avg_dur else 0
        
        prev_new = results.get('prev_new', 0)
        prev_done = results.get('prev_done', 0)
        prev_on_time = results.get('prev_on_time', 0)
        prev_tasks_with_due = results.get('prev_with_due', 0)
        
        prev_avg_dur = results.get('prev_avg_dur')
        prev_avg_time = prev_avg_dur.total_seconds() / 3600 if prev_avg_dur else 0
    
        # 3.3 Derived Rates
        rate_throughput = (metric_done / metric_new * 100) if metric_new else 0
        prev_rate = (prev_done / prev_new * 100) if prev_new else 0
        
        rate_on_time = (metric_on_time / tasks_with_due_in_period * 100) if tasks_with_due_in_period else 0
        prev_rate_on_time = (prev_on_time / prev_tasks_with_due * 100) if prev_tasks_with_due else 0
    
        # 增长计算
        def calc_growth(current, previous):
            if not previous:
                return 100 if current > 0 else 0
            return round(((current - previous) / previous) * 100, 1)
    
        growth_new = calc_growth(metric_new, prev_new)
        growth_done = calc_growth(metric_done, prev_done)
        growth_rate = round(rate_throughput - prev_rate, 1) # 百分比绝对差
        growth_on_time = round(rate_on_time - prev_rate_on_time, 1)
        growth_avg_time = round(metric_avg_time - prev_avg_time, 1) # 小时绝对差
    
        # --- 4. 图表: 趋势分析 ---
        
        chart_start = start_date or (today - timedelta(days=29))
        chart_end = end_date or today
        days_diff = (chart_end - chart_start).days + 1
        
        trend_labels = []
        trend_created = []
        trend_completed = []
        
        # 高效聚合
        # 按日期分组
        created_data = base_tasks.filter(created_at__date__range=(chart_start, chart_end))\
            .values('created_at__date').annotate(c=Count('id'))
        created_map = {item['created_at__date']: item['c'] for item in created_data}
        
        completed_data = base_tasks.filter(completed_at__date__range=(chart_start, chart_end), status__in=[TaskStatus.DONE, TaskStatus.CLOSED])\
            .values('completed_at__date').annotate(c=Count('id'))
        completed_map = {item['completed_at__date']: item['c'] for item in completed_data}
        
        # 填充空缺
        for i in range(days_diff):
            d = chart_start + timedelta(days=i)
            trend_labels.append(d.strftime('%m-%d'))
            trend_created.append(created_map.get(d, 0))
            trend_completed.append(completed_map.get(d, 0))
    
        # --- 5. 分布: 状态与优先级 (活跃任务快照) ---
        dist_qs = base_tasks
        if start_date and end_date:
            dist_qs = dist_qs.filter(created_at__date__range=(start_date, end_date))
            
        status_dist = list(dist_qs.values('status').annotate(c=Count('id')).order_by('-c'))
        status_map = dict(Task.STATUS_CHOICES)
        priority_dist = list(dist_qs.values('priority').annotate(c=Count('id')))
        priority_map = dict(Task.PRIORITY_CHOICES)
    
        # --- 6. 缺失日报 (可操作) ---
        missing_count = 0
        
        if period == 'today' or period == 'custom': # 仅在相关时显示缺失
            # Optimization: Use 'date' field instead of 'created_at__date' for index usage
            reported_ids = DailyReport.objects.filter(date=today).values_list('user_id', flat=True)
            
            # 相关用户
            target_projs = Project.objects.filter(is_active=True)
            target_projs = target_projs.filter(id__in=accessible_projects)
            if project_id and project_id.isdigit():
                target_projs = target_projs.filter(id=int(project_id))
                
            relevant_users = User.objects.filter(is_active=True).filter(
                Q(project_memberships__in=target_projs) | Q(managed_projects__in=target_projs)
            ).distinct()
            
            if user_id: relevant_users = relevant_users.filter(id=int(user_id))
            if role: relevant_users = relevant_users.filter(profile__position=role)
            
            missing_users_qs = relevant_users.exclude(id__in=reported_ids)
            missing_count = missing_users_qs.count()
    
        # --- 7. 详情表 (项目 / 用户) ---
        # 按项目分组
        project_metrics = dist_qs.values('project__id', 'project__name').annotate(
            total=Count('id'),
            completed=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])),
            overdue=Count('id', filter=Q(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS], due_at__lt=now)), # 逾期活跃
            avg_lead=Avg(F('completed_at') - F('created_at'), filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]))
        ).order_by('-total')
        
        project_stats = []
        for row in project_metrics:
            t = row['total']
            c = row['completed']
            lt = row['avg_lead']
            project_stats.append({
                'id': row['project__id'],
                'name': row['project__name'],
                'total': t,
                'completed': c,
                'rate': (c/t*100) if t else 0,
                'overdue': row['overdue'],
                'lead_time': round(lt.total_seconds()/3600, 1) if lt else None
            })
    
        # 按用户分组
        user_metrics = dist_qs.values('user__id', 'user__username', 'user__first_name', 'user__last_name').annotate(
            total=Count('id'),
            completed=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])),
            overdue=Count('id', filter=Q(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS], due_at__lt=now)),
            on_time=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED], due_at__isnull=False, completed_at__lte=F('due_at'))),
            avg_lead=Avg(F('completed_at') - F('created_at'), filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]))
        ).order_by('-total')[:50] # 限制前 50
        
        user_stats = []
        for row in user_metrics:
            t = row['total']
            c = row['completed']
            lt = row['avg_lead']
            user_stats.append({
                'id': row['user__id'],
                'name': f"{row['user__first_name'] or ''} {row['user__last_name'] or ''}".strip() or row['user__username'],
                'total': t,
                'completed': c,
                'rate': (c/t*100) if t else 0,
                'overdue': row['overdue'],
                'on_time': row['on_time'],
                'lead_time': round(lt.total_seconds()/3600, 1) if lt else None
            })
            
        stats_data = {
            'metric_new': metric_new,
            'metric_done': metric_done,
            'metric_overdue': metric_overdue,
            'rate_throughput': rate_throughput,
            'rate_on_time': rate_on_time,
            'metric_avg_time': metric_avg_time,
            'growth_new': growth_new,
            'growth_done': growth_done,
            'growth_rate': growth_rate,
            'growth_on_time': growth_on_time,
            'growth_avg_time': growth_avg_time,
            'missing_count': missing_count,
            'trend_labels': trend_labels,
            'trend_created': trend_created,
            'trend_completed': trend_completed,
            'status_dist': status_dist,
            'priority_dist': priority_dist,
            'project_stats': project_stats,
            'user_stats': user_stats,
        }
        
        cache.set(cache_key, stats_data, 600)
    
    # Unpack from stats_data
    status_map = dict(Task.STATUS_CHOICES)
    priority_map = dict(Task.PRIORITY_CHOICES)

    # --- 8. 上下文 ---
    # 下钻过滤字符串
    # 当点击 "逾期" 时，我们想跳转到具有相同 项目/用户 过滤 + status=overdue 的列表
    base_params = request.GET.copy()
    if 'period' in base_params: del base_params['period'] 
    
    filter_qs = base_params.urlencode()

    return render(request, 'tasks/admin_task_stats.html', {
        'period': period,
        'start_date': start_date,
        'end_date': end_date,
        
        # Metrics
        'kpi': {
            'new': stats_data['metric_new'],
            'new_growth': stats_data['growth_new'],
            'new_growth_abs': abs(stats_data['growth_new']),
            'done': stats_data['metric_done'],
            'done_growth': stats_data['growth_done'],
            'done_growth_abs': abs(stats_data['growth_done']),
            'rate': stats_data['rate_throughput'],
            'rate_growth': stats_data['growth_rate'], 
            'rate_growth_abs': abs(stats_data['growth_rate']),
            'overdue': stats_data['metric_overdue'],
            'missing_reports': stats_data['missing_count'],
            'on_time_rate': stats_data['rate_on_time'],
            'on_time_growth': stats_data['growth_on_time'],
            'on_time_growth_abs': abs(stats_data['growth_on_time']),
            'avg_time': round(stats_data['metric_avg_time'], 1),
            'avg_time_growth': stats_data['growth_avg_time'],
            'avg_time_growth_abs': abs(stats_data['growth_avg_time']),
        },
        
        # Charts
        'trend': {
            'labels': stats_data['trend_labels'],
            'created': stats_data['trend_created'],
            'completed': stats_data['trend_completed'],
        },
        'dist': {
            'status': [{'label': status_map.get(x['status'], x['status']), 'value': x['c'], 'code': x['status']} for x in stats_data['status_dist']],
            'priority': [{'label': priority_map.get(x['priority'], x['priority']), 'value': x['c'], 'code': x['priority']} for x in stats_data['priority_dist']],
        },
        
        # Tables
        'projects_data': stats_data['project_stats'],
        'users_data': stats_data['user_stats'],
        
        # Filters
        'projects': accessible_projects.order_by('name'),
        'role_choices': Profile.ROLE_CHOICES,
        'current_filters': {
            'project': int(project_id) if project_id and project_id.isdigit() else '',
            'user': int(user_id) if user_id and user_id.isdigit() else '',
            'role': role,
            'q': q,
        },
        'drill_down_params': filter_qs,
    })


@login_required
def admin_task_stats_export(request):
    accessible_projects = get_accessible_projects(request.user)
    if not accessible_projects.exists():
        return _admin_forbidden(request, "需要管理员或项目管理员权限 / Admin or project manager required")

    project_id = request.GET.get('project')
    user_id = request.GET.get('user')
    
    start_str = request.GET.get('start')
    end_str = request.GET.get('end')
    q = request.GET.get('q')
    role = request.GET.get('role')

    start_date = parse_date(start_str) if start_str else None
    end_date = parse_date(end_str) if end_str else None

    tasks = Task.objects.select_related('project', 'user')
    tasks = tasks.filter(project__in=accessible_projects)

    if project_id and project_id.isdigit():
        pid = int(project_id)
        if accessible_projects.filter(id=pid).exists():
            tasks = tasks.filter(project_id=pid)
        else:
            tasks = tasks.none()
    if user_id and user_id.isdigit():
        tasks = tasks.filter(user_id=int(user_id))

    if q:
        tasks = tasks.filter(Q(user__username__icontains=q) | Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q))
    if role and role in dict(Profile.ROLE_CHOICES):
        tasks = tasks.filter(user__profile__position=role)
    
    if start_date and end_date:
        tasks = tasks.filter(created_at__date__range=[start_date, end_date])
    elif start_date:
        tasks = tasks.filter(created_at__date__gte=start_date)
    elif end_date:
        tasks = tasks.filter(created_at__date__lte=end_date)

    rows = []
    # 使用与 admin_task_stats 相同的注释逻辑以保持一致性
    grouped = tasks.values('project__name', 'user__username', 'user__first_name', 'user__last_name').annotate(
        total=Count('id'),
        completed=Count('id', filter=Q(status__in=['done', 'closed'])),
        overdue=Count('id', filter=Q(
            status__in=['todo', 'in_progress', 'blocked', 'in_review'], 
            due_at__lt=timezone.now()
        ))
    )
    for g in grouped:
        total = g['total']
        comp = g['completed']
        ovd = g['overdue']
        comp_rate = f"{(comp/total*100):.1f}%" if total else "0%"
        ovd_rate = f"{(ovd/total*100):.1f}%" if total else "0%"
        rows.append([
            g['project__name'] or '',
            g['user__username'],
            f"{g['user__first_name'] or ''} {g['user__last_name'] or ''}".strip(),
            total,
            comp,
            ovd,
            comp_rate,
            ovd_rate,
        ])

    header = ["项目", "用户名", "姓名", "总任务数", "已完成", "逾期", "完成率", "逾期率"]
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="task_stats.csv"'
    log_action(request, 'export', f"task_stats project={project_id} user={user_id}")
    return response

@login_required
def admin_task_create(request):
    user = request.user
    
    # 权限检查：任何可访问的项目
    accessible_projects = get_accessible_projects(user)
    if not accessible_projects.exists():
        return _admin_forbidden(request, "您没有权限创建任务 / No accessible projects")

    # 筛选下拉菜单的项目：仅显示用户可以管理的项目
    # 因为普通成员不能创建任务。
    manageable_projects = get_manageable_projects(user)
    projects_qs = Project.objects.filter(id__in=manageable_projects.values('id'))
        
    projects = projects_qs.annotate(task_count=Count('tasks')).order_by('-task_count', 'name')
    User = get_user_model()
    # 性能优化：不要加载所有用户。
    # user_objs = list(User.objects.all().order_by('username'))
    existing_urls = [u for u in Task.objects.exclude(url='').values_list('url', flat=True).distinct()]

    # 获取任务模板（最新版本）
    task_templates = TaskTemplateVersion.objects.filter(
        version=Subquery(
            TaskTemplateVersion.objects.filter(name=OuterRef('name'))
            .order_by('-version')
            .values('version')[:1]
        ),
        is_shared=True
    ).order_by('name')

    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        url = (request.POST.get('url') or '').strip()
        content = (request.POST.get('content') or '').strip()
        project_id = request.POST.get('project')
        user_id = request.POST.get('user')
        category = request.POST.get('category') or TaskCategory.TASK
        # 如果用户未选择状态（或为空），则根据分类设置默认值
        raw_status = request.POST.get('status')
        if category == TaskCategory.BUG and (not raw_status or raw_status == 'todo'):
             status = TaskStatus.NEW
        else:
             status = raw_status or 'todo'
        
        priority = request.POST.get('priority') or 'medium'
        due_at_str = request.POST.get('due_at')

        # 强制 BUG 的初始状态
        if category == TaskCategory.BUG and status == TaskStatus.TODO:
            status = TaskStatus.NEW

        errors = []
        if not title:
            errors.append("请输入任务标题")
        if not url and not content:
            errors.append("任务内容需填写：请选择 URL 或填写文本内容")
        if status not in dict(Task.STATUS_CHOICES):
            errors.append("请选择有效的状态")
        if category not in dict(Task.CATEGORY_CHOICES):
            errors.append("请选择有效的分类")
        if priority not in dict(Task.PRIORITY_CHOICES):
            errors.append("请选择有效的优先级")
        project = None
        target_user = None
        if project_id and project_id.isdigit():
            project = Project.objects.filter(id=int(project_id)).first()
        
        if not project:
            errors.append("请选择项目")
        else:
            # 检查用户是否可以管理此项目（以创建任务）
            if not can_manage_project(request.user, project):
                 errors.append("您没有权限在此项目发布任务 (需管理员或负责人权限)")
            
        if user_id and user_id.isdigit():
            target_user = User.objects.filter(id=int(user_id)).first()
        if not target_user:
            errors.append("请选择目标用户")

        collaborator_ids = request.POST.getlist('collaborators')
        collaborators = []
        if collaborator_ids:
            collaborators = User.objects.filter(id__in=collaborator_ids)

        due_at = None
        if due_at_str:
            try:
                parsed = datetime.fromisoformat(due_at_str)
                due_at = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
            except ValueError:
                errors.append("完成时间格式不正确，请使用日期时间选择器")

        if errors:
            return render(request, 'tasks/admin_task_form.html', {
                'errors': errors,
                'projects': projects,
                'task_templates': task_templates,
                'users': collaborators,
                'task_status_choices': Task.STATUS_CHOICES,
                'task_category_choices': Task.CATEGORY_CHOICES,
                'task_priority_choices': Task.PRIORITY_CHOICES,
                'existing_urls': existing_urls,
                'form_values': {'title': title, 'url': url, 'content': content, 'project_id': project_id, 'user_id': user_id, 'category': category, 'status': status, 'priority': priority, 'due_at': due_at_str, 'collaborator_ids': collaborator_ids},
            })

        task = Task.objects.create(
            title=title,
            url=url,
            content=content,
            project=project,
            user=target_user,
            category=category,
            status=status,
            priority=priority,
            due_at=due_at,
        )
        
        if collaborators:
            task.collaborators.set(collaborators)

        # 处理附件
        for f in request.FILES.getlist('attachments'):
            TaskAttachment.objects.create(
                task=task,
                user=request.user,
                file=f
            )

        log_action(request, 'create', f"task {task.id}")
        return redirect('tasks:admin_task_list')

    return render(request, 'tasks/admin_task_form.html', {
        'projects': projects,
        'users': [],
        'task_templates': task_templates,
        'task_status_choices': Task.STATUS_CHOICES,
        'task_category_choices': Task.CATEGORY_CHOICES,
        'task_priority_choices': Task.PRIORITY_CHOICES,
        'existing_urls': existing_urls,
        'form_values': {
            'project_id': request.GET.get('project_id'),
            'category': request.GET.get('category'), # 允许预填充类别
            'status': TaskStatus.NEW if request.GET.get('category') == 'BUG' else None, # 如果是 BUG，预填充状态
        },
    })


@login_required
def admin_task_edit(request, pk):
    # 尝试获取任务
    try:
        task = Task.objects.select_related('project').get(pk=pk)
    except Task.DoesNotExist:
        raise Http404
        
    user = request.user
    
    # 检查用户是否可以看到此任务 (基本可见性)
    # 1. 检查可见性：用户能看到这个任务吗？
    #    - 超级用户：是。
    #    - 项目可访问（成员/拥有者/管理者）：是。
    #    - 任务拥有者/协作者：是。
    #    如果 否 -> 404。
    
    can_see = get_accessible_projects(user).filter(id=task.project.id).exists() or \
              task.user == user or \
              task.collaborators.filter(pk=user.pk).exists()
              
    if not can_see:
        raise Http404
            
    # 检查权限（超级用户，项目拥有者/管理者，任务拥有者，或协作者）
    # 注意：普通成员可以编辑他们自己的任务或如果他们是协作者。
    # 但他们不能编辑与他们无关的任务，即使是在同一个项目中。
    can_manage = can_manage_project(user, task.project) or \
                 task.user == user or \
                 task.collaborators.filter(pk=user.pk).exists()
                 
    if not can_manage:
        return _admin_forbidden(request)

    # 权限检查：仅限协作者的限制
    can_full_edit = can_manage_project(user, task.project) or \
                    task.user == user
    is_collaborator_only = not can_full_edit and task.collaborators.filter(pk=user.pk).exists()

    manageable_projects = get_manageable_projects(user)
    projects_qs = Project.objects.filter(id__in=manageable_projects.values('id'))
        
    projects = projects_qs.annotate(task_count=Count('tasks')).order_by('-task_count', 'name')
    User = get_user_model()
    existing_urls = [u for u in Task.objects.exclude(url='').values_list('url', flat=True).distinct()]

    if request.method == 'POST':
        # 强制执行仅限协作者的限制：检查他们是否试图绕过 UI
        if is_collaborator_only:
             if 'title' in request.POST and (request.POST.get('title') or '').strip() != task.title:
                 return _admin_forbidden(request, "权限不足：协作人无法修改任务标题")
             if 'project' in request.POST and request.POST.get('project') and int(request.POST.get('project')) != task.project.id:
                 return _admin_forbidden(request, "权限不足：协作人无法移动项目")
             if 'user' in request.POST and request.POST.get('user') and int(request.POST.get('user')) != task.user.id:
                 return _admin_forbidden(request, "权限不足：协作人无法转让负责人")
        
        # 捕获旧状态用于历史记录
        old_status = task.status
        old_due = task.due_at
        old_user = task.user
        
        category = request.POST.get('category') or TaskCategory.TASK
        status = request.POST.get('status') or 'todo'
        priority = request.POST.get('priority') or 'medium'
        errors = []
        
        if is_collaborator_only:
            # 使用现有值
            title = task.title
            url = task.url
            content = task.content
            project = task.project
            target_user = task.user
            category = task.category
            due_at = task.due_at
            priority = task.priority
            collaborators = list(task.collaborators.all())
        else:
            title = (request.POST.get('title') or '').strip()
            url = (request.POST.get('url') or '').strip()
            content = (request.POST.get('content') or '').strip()
            project_id = request.POST.get('project')
            user_id = request.POST.get('user')
            due_at_str = request.POST.get('due_at')

            if not title:
                errors.append("请输入任务标题")
            if not url and not content:
                errors.append("任务内容需填写：请选择 URL 或填写文本内容")
            
            project = None
            target_user = None
            if project_id and project_id.isdigit():
                project = Project.objects.filter(id=int(project_id)).first()
            if not project:
                errors.append("请选择项目")
            else:
                 if project.id != task.project.id:
                     if not can_manage_project(user, project):
                         errors.append("您没有权限移动任务到此项目 (需目标项目管理权限)")

            if user_id and user_id.isdigit():
                target_user = User.objects.filter(id=int(user_id)).first()
            if not target_user:
                errors.append("请选择目标用户")

            collaborator_ids = request.POST.getlist('collaborators')
            collaborators = []
            if collaborator_ids:
                collaborators = User.objects.filter(id__in=collaborator_ids)

            due_at = None
            if due_at_str:
                try:
                    parsed = datetime.fromisoformat(due_at_str)
                    due_at = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
                except ValueError:
                    errors.append("完成时间格式不正确，请使用日期时间选择器")

        if status not in dict(Task.STATUS_CHOICES):
            errors.append("请选择有效的状态")
        if category not in dict(Task.CATEGORY_CHOICES):
            errors.append("请选择有效的分类")
        if not is_collaborator_only and priority not in dict(Task.PRIORITY_CHOICES):
            errors.append("请选择有效的优先级")

        if errors:
            return render(request, 'tasks/admin_task_form.html', {
                'task': task,
                'is_collaborator_only': is_collaborator_only,
                'errors': errors,
                'projects': projects,
                'users': collaborators if not is_collaborator_only else task.collaborators.all(),
                'task_status_choices': Task.STATUS_CHOICES,
                'task_category_choices': Task.CATEGORY_CHOICES,
                'task_priority_choices': Task.PRIORITY_CHOICES,
                'existing_urls': existing_urls,
                'form_values': {
                    'title': title, 
                    'url': url, 
                    'content': content, 
                    'project_id': project.id if project else '', 
                    'user_id': target_user.id if target_user else '', 
                    'category': category,
                    'status': status, 
                    'priority': priority,
                    'due_at': due_at.isoformat() if due_at else '', 
                    'collaborator_ids': [c.id for c in collaborators]
                },
            })

        # 更新任务
        task.title = title
        task.url = url
        task.content = content
        task.project = project
        task.user = target_user
        task.category = category
        task.status = status
        task.priority = priority
        task.due_at = due_at
        task.save()
        
        task.collaborators.set(collaborators)

        # 处理附件（仅在非仅限协作者时允许上传）
        if not is_collaborator_only:
            for f in request.FILES.getlist('attachments'):
                TaskAttachment.objects.create(
                    task=task,
                    user=request.user,
                    file=f
                )

        log_action(request, 'update', f"task {task.id}")
        return redirect('tasks:task_view', pk=task.id)

    return render(request, 'tasks/admin_task_form.html', {
        'task': task,
        'is_collaborator_only': is_collaborator_only,
        'projects': projects,
        'users': task.collaborators.all(),
        'task_status_choices': Task.STATUS_CHOICES,
        'task_category_choices': Task.CATEGORY_CHOICES,
        'task_priority_choices': Task.PRIORITY_CHOICES,
        'existing_urls': existing_urls,
        'form_values': {
            'title': task.title,
            'url': task.url,
            'content': task.content,
            'project_id': task.project_id,
            'user_id': task.user_id,
            'category': task.category,
            'status': task.status,
            'priority': task.priority,
            'due_at': task.due_at.isoformat() if task.due_at else '',
            'collaborator_ids': list(task.collaborators.values_list('id', flat=True))
        },
    })
