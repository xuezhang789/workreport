from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.contrib import messages
from django.http import JsonResponse
import json
from datetime import timedelta

from work_logs.models import DailyReport
from projects.models import Project
from core.models import Profile
from reports.forms import ReportTemplateForm
from reports.utils import get_accessible_projects, get_accessible_reports, can_manage_project
from core.utils import _admin_forbidden, _friendly_forbidden, has_manage_permission
from audit.utils import log_action

def _filtered_reports(request):
    """Return filtered queryset plus filter values."""
    role = (request.GET.get('role') or '').strip()
    start_date = parse_date(request.GET.get('start_date') or '')
    end_date = parse_date(request.GET.get('end_date') or '')

    qs = DailyReport.objects.select_related('user').prefetch_related('projects').order_by('-date', '-created_at')
    if role:
        qs = qs.filter(role=role)
    if start_date:
        qs = qs.filter(date__gte=start_date)
    if end_date:
        qs = qs.filter(date__lte=end_date)
    return qs, role, start_date, end_date


def _build_sections(report):
    return {
        'dev': [
            ('今日完成工作 / Work Completed Today', report.today_work),
            ('今日进展 & 问题 / Progress & Issues', report.progress_issues),
            ('明日工作计划 / Plan for Tomorrow', report.tomorrow_plan),
        ],
        'qa': [
            ('今日测试范围 / Today’s Testing Scope', report.testing_scope),
            ('测试完成情况 / Testing Progress', report.testing_progress),
            ('Bug 统计 / Bug Summary', report.bug_summary),
            ('明日测试计划 / Plan for Tomorrow', report.testing_tomorrow),
        ],
        'pm': [
            ('今日产品推进内容 / Product Progress Today', report.product_today),
            ('今日协调 / 决策事项 / Coordination & Decisions', report.product_coordination),
            ('明日计划 / Plan for Tomorrow', report.product_tomorrow),
        ],
        'ui': [
            ('今日完成设计 / Designs Completed Today', report.ui_today),
            ('反馈与修改 / Feedback & Revisions', report.ui_feedback),
            ('明日计划 / Plan for Tomorrow', report.ui_tomorrow),
        ],
        'ops': [
            ('今日运维工作 / Operations Tasks Today', report.ops_today),
            ('监控与故障情况 / Monitoring & Incidents', report.ops_monitoring),
            ('明日计划 / Plan for Tomorrow', report.ops_tomorrow),
        ],
        'mgr': [
            ('今日项目进度概览 / Project Progress Overview', report.mgr_progress),
            ('风险与阻塞点 / Risks & Blockers', report.mgr_risks),
            ('明日推进重点 / Key Focus for Tomorrow', report.mgr_tomorrow),
        ],
    }.get(report.role, [])


def _has_role_content(role: str, payload: dict) -> bool:
    role_fields = {
        'dev': ['today_work', 'progress_issues', 'tomorrow_plan'],
        'qa': ['testing_scope', 'testing_progress', 'bug_summary', 'testing_tomorrow'],
        'pm': ['product_today', 'product_coordination', 'product_tomorrow'],
        'ui': ['ui_today', 'ui_feedback', 'ui_tomorrow'],
        'ops': ['ops_today', 'ops_monitoring', 'ops_tomorrow'],
        'mgr': ['mgr_progress', 'mgr_risks', 'mgr_tomorrow'],
    }
    fields = role_fields.get(role, [])
    return any((payload.get(f, '') or '').strip() for f in fields)


def _report_initial(report: DailyReport | None):
    if not report:
        return {}
    return {
        'date': report.date,
        'role': report.role,
        'today_work': report.today_work,
        'progress_issues': report.progress_issues,
        'tomorrow_plan': report.tomorrow_plan,
        'testing_scope': report.testing_scope,
        'testing_progress': report.testing_progress,
        'bug_summary': report.bug_summary,
        'testing_tomorrow': report.testing_tomorrow,
        'product_today': report.product_today,
        'product_coordination': report.product_coordination,
        'product_tomorrow': report.product_tomorrow,
        'ui_today': report.ui_today,
        'ui_feedback': report.ui_feedback,
        'ui_tomorrow': report.ui_tomorrow,
        'ops_today': report.ops_today,
        'ops_monitoring': report.ops_monitoring,
        'ops_tomorrow': report.ops_tomorrow,
        'mgr_progress': report.mgr_progress,
        'mgr_risks': report.mgr_risks,
        'mgr_tomorrow': report.mgr_tomorrow,
        'status': report.status,
    }

@login_required
def daily_report_create(request):
    user = request.user
    try:
        position = user.profile.position
    except Profile.DoesNotExist:
        position = 'dev'

    project_filter = Q(is_active=True)
    if not has_manage_permission(user):
        # project_filter &= (Q(members=user) | Q(managers=user) | Q(owner=user))
        accessible_projects = get_accessible_projects(user)
        project_filter &= Q(id__in=accessible_projects.values('id'))
        
    projects_qs = Project.objects.filter(project_filter).annotate(
        user_used=Count('reports', filter=Q(reports__user=user))
    ).distinct().order_by('-user_used', 'name')
    latest_report = DailyReport.objects.filter(user=user).order_by('-date', '-created_at').first()
    selected_project_ids = list(latest_report.projects.values_list('id', flat=True)) if latest_report else []
    role_value = position
    date_value = ''
    errors = []
    initial_values = {}

    existing_report = None
    # 防止重复日报：同一用户+日期+角色唯一

    if request.method == 'POST':
        date_str = request.POST.get('date')
        role = request.POST.get('role') or position
        role_value = role
        date_value = date_str
        project_ids = [int(pid) for pid in request.POST.getlist('projects') if pid.isdigit()]
        
        if not has_manage_permission(user) and project_ids:
            accessible_ids = set(get_accessible_projects(user).values_list('id', flat=True))
            if not set(project_ids).issubset(accessible_ids):
                errors.append("您选择了无效或无权限的项目 / Invalid or unauthorized projects selected")

        edit_report_id = request.POST.get('report_id')

        # 通用
        today_work = request.POST.get('today_work', '')
        progress_issues = request.POST.get('progress_issues', '')
        tomorrow_plan = request.POST.get('tomorrow_plan', '')

        # QA
        testing_scope = request.POST.get('testing_scope', '')
        testing_progress = request.POST.get('testing_progress', '')
        bug_summary = request.POST.get('bug_summary', '')
        testing_tomorrow = request.POST.get('testing_tomorrow', '')

        # 产品
        product_today = request.POST.get('product_today', '')
        product_coordination = request.POST.get('product_coordination', '')
        product_tomorrow = request.POST.get('product_tomorrow', '')

        # UI
        ui_today = request.POST.get('ui_today', '')
        ui_feedback = request.POST.get('ui_feedback', '')
        ui_tomorrow = request.POST.get('ui_tomorrow', '')

        # 运维
        ops_today = request.POST.get('ops_today', '')
        ops_monitoring = request.POST.get('ops_monitoring', '')
        ops_tomorrow = request.POST.get('ops_tomorrow', '')

        # 管理
        mgr_progress = request.POST.get('mgr_progress', '')
        mgr_risks = request.POST.get('mgr_risks', '')
        mgr_tomorrow = request.POST.get('mgr_tomorrow', '')

        if not role or role not in dict(DailyReport.ROLE_CHOICES):
            errors.append("请选择有效的角色")
        if date_str:
            parsed_date = parse_date(date_str)
            if not parsed_date:
                errors.append("日期格式不正确")
                parsed_date = None
        else:
            errors.append("请填写日期")
            parsed_date = None

        if not _has_role_content(role, {
            'today_work': today_work,
            'progress_issues': progress_issues,
            'tomorrow_plan': tomorrow_plan,
            'testing_scope': testing_scope,
            'testing_progress': testing_progress,
            'bug_summary': bug_summary,
            'testing_tomorrow': testing_tomorrow,
            'product_today': product_today,
            'product_coordination': product_coordination,
            'product_tomorrow': product_tomorrow,
            'ui_today': ui_today,
            'ui_feedback': ui_feedback,
            'ui_tomorrow': ui_tomorrow,
            'ops_today': ops_today,
            'ops_monitoring': ops_monitoring,
            'ops_tomorrow': ops_tomorrow,
            'mgr_progress': mgr_progress,
            'mgr_risks': mgr_risks,
            'mgr_tomorrow': mgr_tomorrow,
        }):
            errors.append("请填写与角色对应的内容，至少一项")

        if parsed_date and not edit_report_id:
        # 已存在同日期同角色时报错，引导去编辑
            existing_report = DailyReport.objects.filter(user=user, date=parsed_date, role=role).first()
            if existing_report:
                errors.append("该日期、该角色的日报已存在，请编辑已有日报。")

        if errors:
            for e in errors:
                messages.error(request, e)
            context = {
                'user_position': position,
                'projects': projects_qs,
                'selected_project_ids': project_ids or selected_project_ids,
                'role_value': role_value,
                'date_value': date_value,
                'errors': errors,
                'form_user': user,
                'initial_values': {
                    'today_work': today_work,
                    'progress_issues': progress_issues,
                    'tomorrow_plan': tomorrow_plan,
                    'testing_scope': testing_scope,
                    'testing_progress': testing_progress,
                    'bug_summary': bug_summary,
                    'testing_tomorrow': testing_tomorrow,
                    'product_today': product_today,
                    'product_coordination': product_coordination,
                    'product_tomorrow': product_tomorrow,
                    'ui_today': ui_today,
                    'ui_feedback': ui_feedback,
                    'ui_tomorrow': ui_tomorrow,
                    'ops_today': ops_today,
                    'ops_monitoring': ops_monitoring,
                    'ops_tomorrow': ops_tomorrow,
                    'mgr_progress': mgr_progress,
                    'mgr_risks': mgr_risks,
                    'mgr_tomorrow': mgr_tomorrow,
                },
                'existing_report': existing_report,
            }
            return render(request, 'reports/daily_report_form.html', context)

        date = parsed_date or timezone.now().date()
        status = 'draft' if request.POST.get('submit_action') == 'draft' else 'submitted'

        if edit_report_id:
            report = get_object_or_404(DailyReport, pk=edit_report_id)
            if not (report.user == request.user or has_manage_permission(request.user)):
                return _friendly_forbidden(request, "无权限编辑该日报 / No permission to edit this report")
            conflict_exists = DailyReport.objects.filter(user=user, date=date, role=role).exclude(pk=report.pk).exists()
            # 编辑时避免与其他日报冲突
            if conflict_exists:
                errors.append("已存在相同日期与角色的日报，请调整日期或角色后再保存。")
                for e in errors:
                    messages.error(request, e)
                context = {
                    'user_position': position,
                    'projects': projects_qs,
                    'selected_project_ids': project_ids or selected_project_ids,
                    'role_value': role_value,
                    'date_value': date_value,
                    'errors': errors,
                    'initial_values': _report_initial(report),
                    'form_user': user,
                    'report_id': report.id,
                }
                return render(request, 'reports/daily_report_form.html', context)
            report.date = date
            report.role = role
            report.today_work = today_work
            report.progress_issues = progress_issues
            report.tomorrow_plan = tomorrow_plan
            report.testing_scope = testing_scope
            report.testing_progress = testing_progress
            report.bug_summary = bug_summary
            report.testing_tomorrow = testing_tomorrow
            report.product_today = product_today
            report.product_coordination = product_coordination
            report.product_tomorrow = product_tomorrow
            report.ui_today = ui_today
            report.ui_feedback = ui_feedback
            report.ui_tomorrow = ui_tomorrow
            report.ops_today = ops_today
            report.ops_monitoring = ops_monitoring
            report.ops_tomorrow = ops_tomorrow
            report.mgr_progress = mgr_progress
            report.mgr_risks = mgr_risks
            report.mgr_tomorrow = mgr_tomorrow
            report.status = status
            report.project = ''
            report.save()
        else:
            report, _ = DailyReport.objects.update_or_create(
                user=user,
                date=date,
                role=role,
                defaults={
                    'project': '',
                    'today_work': today_work,
                    'progress_issues': progress_issues,
                    'tomorrow_plan': tomorrow_plan,
                    'testing_scope': testing_scope,
                    'testing_progress': testing_progress,
                    'bug_summary': bug_summary,
                    'testing_tomorrow': testing_tomorrow,
                    'product_today': product_today,
                    'product_coordination': product_coordination,
                    'product_tomorrow': product_tomorrow,
                    'ui_today': ui_today,
                    'ui_feedback': ui_feedback,
                    'ui_tomorrow': ui_tomorrow,
                    'ops_today': ops_today,
                    'ops_monitoring': ops_monitoring,
                    'ops_tomorrow': ops_tomorrow,
                    'mgr_progress': mgr_progress,
                    'mgr_risks': mgr_risks,
                    'mgr_tomorrow': mgr_tomorrow,
                    'status': status,
                }
            )
        if project_ids:
            report.projects.set(project_ids)
        else:
            report.projects.clear()

        return redirect('reports:my_reports')

    context = {
        'user_position': position,
        'projects': projects_qs,
        'selected_project_ids': selected_project_ids,
        'role_value': role_value,
        'date_value': date_value,
        'errors': errors,
        'initial_values': initial_values,
        'form_user': user,
    }
    return render(request, 'reports/daily_report_form.html', context)


@login_required
def my_reports(request):
    start_date = parse_date(request.GET.get('start_date') or '')
    end_date = parse_date(request.GET.get('end_date') or '')
    status = (request.GET.get('status') or '').strip()
    project_id = request.GET.get('project')
    role = (request.GET.get('role') or '').strip()
    q = (request.GET.get('q') or '').strip()

    qs = DailyReport.objects.filter(user=request.user).select_related('user').prefetch_related('projects', 'user__profile').order_by('-date', '-created_at')
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

    paginator = Paginator(qs, 9)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    today = timezone.localdate()
    has_today = qs.filter(date=today).exists()
    # streak: count consecutive days back from today with submitted, independent of filters
    streak_qs = DailyReport.objects.filter(user=request.user, status='submitted').values_list('date', flat=True).order_by('-date')
    dates = list(streak_qs)
    streak = 0
    curr = today
    date_set = set(dates)
    while curr in date_set:
        streak += 1
        curr = curr - timedelta(days=1)

    context = {
        'reports': page_obj,
        'page_obj': page_obj,
        'start_date': start_date,
        'end_date': end_date,
        'status': status,
        'project_id': int(project_id) if project_id and project_id.isdigit() else '',
        'role': role,
        'q': q,
        'total_count': qs.count(),
        'latest_date': qs.first().date if qs.exists() else None,
        'projects': Project.objects.filter(
            Q(members=request.user) | Q(owner=request.user) | Q(managers=request.user) | Q(is_active=True)
        ).annotate(user_used=Count('reports', filter=Q(reports__user=request.user))).distinct().order_by('-user_used', 'name'),
        'has_today': has_today,
        'streak': streak,
    }
    return render(request, 'reports/my_reports.html', context)


@login_required
def report_detail(request, pk: int):
    qs = DailyReport.objects.select_related('user').prefetch_related('projects')
    if has_manage_permission(request.user):
        report = get_object_or_404(qs, pk=pk)
    else:
        report = get_object_or_404(qs, pk=pk)
        can_manage_project = report.projects.filter(managers=request.user).exists()
        if not (report.user == request.user or can_manage_project):
            return _friendly_forbidden(request, "无权限查看该日报 / No permission to view this report")

    sections = _build_sections(report)

    context = {
        'report': report,
        'sections': sections,
        'can_submit': report.status == 'draft' and (report.user == request.user or has_manage_permission(request.user)),
    }
    return render(request, 'reports/report_detail.html', context)


@login_required
def report_submit(request, pk: int):
    report = get_object_or_404(DailyReport, pk=pk)
    if not (report.user == request.user or has_manage_permission(request.user)):
        return _friendly_forbidden(request, "无权限提交该日报 / No permission to submit this report")
    report.status = 'submitted'
    report.save(update_fields=['status', 'updated_at'])
    return redirect('reports:report_detail', pk=pk)


@login_required
def report_edit(request, pk: int):
    report = get_object_or_404(DailyReport.objects.select_related('user').prefetch_related('projects'), pk=pk)
    if not (report.user == request.user or has_manage_permission(request.user)):
        return _friendly_forbidden(request, "无权限编辑该日报 / No permission to edit this report")

    position = getattr(getattr(report.user, 'profile', None), 'position', 'dev')
    project_filter = Q(is_active=True)
    if not has_manage_permission(request.user):
        project_filter &= (Q(owner=request.user) | Q(members=request.user) | Q(managers=request.user))
    projects_qs = Project.objects.filter(project_filter).distinct().order_by('name')
    selected_project_ids = list(report.projects.values_list('id', flat=True))
    errors = []

    if request.method == 'POST':
        return daily_report_create(request)  # reuse logic by same endpoint?  # noqa

    context = {
        'user_position': position,
        'projects': projects_qs,
        'selected_project_ids': selected_project_ids,
        'role_value': report.role,
        'date_value': report.date,
        'errors': errors,
        'initial_values': _report_initial(report),
        'editing': True,
        'report_id': report.id,
        'form_user': report.user,
    }
    return render(request, 'reports/daily_report_form.html', context)


@login_required
def admin_reports(request):
    # Unified Report View: Superuser sees all, others see accessible
    reports, role, start_date, end_date = _filtered_reports(request)
    
    # 权限控制：如果不是超级管理员，仅显示其有权管理的项目的日报
    if not request.user.is_superuser:
        accessible_reports = get_accessible_reports(request.user)
        # 使用 id__in 进行过滤，确保只有相关日报可见
        reports = reports.filter(id__in=accessible_reports.values('id'))

    username = (request.GET.get('username') or '').strip()
    user_id = request.GET.get('user')
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
    if user_id and user_id.isdigit():
        reports = reports.filter(user_id=int(user_id))
    if status in dict(DailyReport.STATUS_CHOICES):
        reports = reports.filter(status=status)

    # 聚合统计数据
    total_count = reports.count()
    submitted_count = reports.filter(status='submitted').count()
    draft_count = reports.filter(status='draft').count()

    paginator = Paginator(reports, 15)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    # 获取项目列表：仅显示用户有权管理或参与的活跃项目
    if request.user.is_superuser:
        projects = Project.objects.filter(is_active=True).order_by('name')
    else:
        projects = get_accessible_projects(request.user).order_by('name')

    log_action(request, 'access', f"admin_reports count={total_count} role={role} start={start_date} end={end_date} username={username} project={project_id} status={status}")
    context = {
        'reports': page_obj,
        'page_obj': page_obj,
        'total_count': total_count,
        'submitted_count': submitted_count,
        'draft_count': draft_count,
        'report_role_choices': DailyReport.ROLE_CHOICES,
        'role': role,
        'start_date': start_date,
        'end_date': end_date,
        'username': username,
        'user_id': int(user_id) if user_id and user_id.isdigit() else '',
        'project_id': int(project_id) if project_id and project_id.isdigit() else '',
        'projects': projects,
        'users': get_user_model().objects.order_by('username'),
        'status': status,
    }
    return render(request, 'reports/admin_reports.html', context)

@login_required
def daily_report_batch_create(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            reports_data = data.get('reports', [])
            created_count = 0
            errors = []
            
            # Get user's role/position
            try:
                role = request.user.profile.position
            except (Profile.DoesNotExist, AttributeError):
                role = 'dev'

            for index, item in enumerate(reports_data):
                date_str = item.get('date')
                project_ids = item.get('projects', [])
                content = item.get('content', '')
                plan = item.get('plan', '')
                
                if not date_str:
                    errors.append(f"第 {index + 1} 行：日期不能为空")
                    continue
                
                try:
                    report_date = parse_date(date_str)
                    if not report_date:
                        raise ValueError
                except (ValueError, TypeError):
                    errors.append(f"第 {index + 1} 行：日期格式无效")
                    continue

                if DailyReport.objects.filter(user=request.user, date=report_date, role=role).exists():
                     errors.append(f"第 {index + 1} 行：{date_str} 的日报已存在")
                     continue
                
                # Create report
                report = DailyReport(
                    user=request.user,
                    date=report_date,
                    role=role,
                    today_work=content,
                    tomorrow_plan=plan,
                    status='submitted'
                )
                report.save()
                
                if project_ids:
                    # Filter valid project IDs (must be accessible)
                    valid_projects = get_accessible_projects(request.user).filter(id__in=project_ids)
                    report.projects.set(valid_projects)
                
                created_count += 1
            
            if errors:
                return JsonResponse({'success': False, 'message': '部分日报创建失败', 'errors': errors, 'created_count': created_count})
            
            return JsonResponse({'success': True, 'message': f'成功创建 {created_count} 份日报'})

        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)
