from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Count, Case, When, IntegerField, Exists, OuterRef, Prefetch
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.contrib import messages
from django.http import JsonResponse
from django.db import transaction
import json
from datetime import timedelta

from work_logs.models import DailyReport
from projects.models import Project
from core.models import Profile
from reports.forms import ReportTemplateForm
from reports.utils import get_accessible_projects, get_accessible_reports, can_manage_project
from core.utils import _admin_forbidden, _friendly_forbidden
from core.permissions import has_manage_permission
from audit.utils import log_action

def _filtered_reports(request):
    """
    返回过滤后的查询集及过滤参数值。
    """
    role = (request.GET.get('role') or '').strip()
    start_date = parse_date(request.GET.get('start_date') or '')
    end_date = parse_date(request.GET.get('end_date') or '')

    qs = DailyReport.objects.select_related('user', 'user__profile').prefetch_related(
        Prefetch('projects', queryset=Project.objects.only('name'))
    ).order_by('-date', '-created_at')
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
@transaction.atomic
def daily_report_create(request):
    user = request.user
    try:
        position = user.profile.position
    except Profile.DoesNotExist:
        position = 'dev'

    project_filter = Q(is_active=True)
    if not has_manage_permission(user):
        # Combine RBAC and direct assignment for robustness
        accessible_projects = get_accessible_projects(user)
        project_filter &= (
            Q(id__in=accessible_projects.values('id')) | 
            Q(owner=user) | 
            Q(members=user) | 
            Q(managers=user)
        )
    
    # 优化：移除昂贵的 annotate(Count)。
    # 策略：加载“最近项目”+“分配项目”，限制为50个。
    
    # 1. 最近项目 ID（来自最近 100 份日报，高效连接）
    recent_pids = list(DailyReport.projects.through.objects.filter(
        dailyreport__user=user
    ).order_by('-dailyreport_id').values_list('project_id', flat=True)[:100])
    
    # 2. 分配的项目（成员/负责人/经理）
    # 如果是超级管理员，accessible_projects 是全部，但严格来说我们应该显示他们可能使用的项目。
    # 对于超级管理员，“Assigned”可能为空，如果他们只是管理员。
    # 所以我们坚持使用 project_filter（超级管理员为全部，其他人为可访问）。
    
    # 我们从 project_filter 获取 ID，但如果超过 1万个则不能全部获取。
    # 所以我们优先获取最近使用的。
    
    final_pids = []
    seen = set()
    
    # 优先添加最近的有效项目
    # 我们需要确保最近的项目仍然处于激活状态且可访问
    valid_recent = Project.objects.filter(project_filter, id__in=recent_pids).values_list('id', flat=True)
    valid_recent_set = set(valid_recent)
    
    # 保持最近顺序
    for pid in recent_pids:
        if pid in valid_recent_set and pid not in seen:
            final_pids.append(pid)
            seen.add(pid)
            
    # 添加其他可访问项目（总数限制为 50）
    remaining_limit = 50 - len(final_pids)
    if remaining_limit > 0:
        others = Project.objects.filter(project_filter).exclude(id__in=seen).order_by('name').values_list('id', flat=True)[:remaining_limit]
        final_pids.extend(others)
        
    # 获取对象并保持顺序
    projects_map = {p.id: p for p in Project.objects.filter(id__in=final_pids)}
    projects_list = [projects_map[pid] for pid in final_pids if pid in projects_map]

    latest_report = DailyReport.objects.filter(user=user).order_by('-date', '-created_at').first()
    selected_project_ids = list(latest_report.projects.values_list('id', flat=True)) if latest_report else []
    role_value = position
    date_value = ''
    errors = []
    initial_values = {}

    existing_report = None
    # 防止重复日报：同一用户+日期+角色唯一

    if request.method == 'POST':
        date_str = request.POST.get('date', '').strip()
        role = (request.POST.get('role') or '').strip() or position
        role_value = role
        date_value = date_str
        project_ids = [int(pid) for pid in request.POST.getlist('projects') if pid.isdigit()]
        
        if not has_manage_permission(user) and project_ids:
            accessible_ids = set(get_accessible_projects(user).values_list('id', flat=True))
            if not set(project_ids).issubset(accessible_ids):
                errors.append("您选择了无效或无权限的项目 / Invalid or unauthorized projects selected")

        edit_report_id = request.POST.get('report_id')

        # 通用
        today_work = request.POST.get('today_work', '').strip()
        progress_issues = request.POST.get('progress_issues', '').strip()
        tomorrow_plan = request.POST.get('tomorrow_plan', '').strip()

        # QA
        testing_scope = request.POST.get('testing_scope', '').strip()
        testing_progress = request.POST.get('testing_progress', '').strip()
        bug_summary = request.POST.get('bug_summary', '').strip()
        testing_tomorrow = request.POST.get('testing_tomorrow', '').strip()

        # 产品
        product_today = request.POST.get('product_today', '').strip()
        product_coordination = request.POST.get('product_coordination', '').strip()
        product_tomorrow = request.POST.get('product_tomorrow', '').strip()

        # UI
        ui_today = request.POST.get('ui_today', '').strip()
        ui_feedback = request.POST.get('ui_feedback', '').strip()
        ui_tomorrow = request.POST.get('ui_tomorrow', '').strip()

        # 运维
        ops_today = request.POST.get('ops_today', '').strip()
        ops_monitoring = request.POST.get('ops_monitoring', '').strip()
        ops_tomorrow = request.POST.get('ops_tomorrow', '').strip()

        # 管理
        mgr_progress = request.POST.get('mgr_progress', '').strip()
        mgr_risks = request.POST.get('mgr_risks', '').strip()
        mgr_tomorrow = request.POST.get('mgr_tomorrow', '').strip()

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
                'projects': projects_list,
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
                    'projects': projects_list,
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
        'projects': projects_list,
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

    try:
        per_page = int(request.GET.get('per_page', 20))
        if per_page not in [10, 20, 50, 100]:
            per_page = 20
    except (ValueError, TypeError):
        per_page = 20

    paginator = Paginator(qs, per_page)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    today = timezone.localdate()
    has_today = qs.filter(date=today).exists()
    
    # Optimized streak calculation: Fetch distinct dates only, limited to 365 days
    # 优化连胜计算：仅获取不重复的日期，限制为365天
    streak_qs = DailyReport.objects.filter(user=request.user, status='submitted').values_list('date', flat=True).distinct().order_by('-date')[:365]
    dates = list(streak_qs)
    
    streak = 0
    curr = today
    date_set = set(dates)
    
    # Simple check for today/yesterday continuity
    # 简单的今天/昨天连续性检查
    if curr in date_set:
        streak += 1
        curr = curr - timedelta(days=1)
        while curr in date_set:
            streak += 1
            curr = curr - timedelta(days=1)
    elif (curr - timedelta(days=1)) in date_set:
         # If today not submitted, check if streak ended yesterday
         # 如果今天未提交，检查连胜是否在昨天结束
         curr = curr - timedelta(days=1)
         while curr in date_set:
            streak += 1
            curr = curr - timedelta(days=1)

    # Optimized Project List: Remove expensive Count annotation
    # 优化项目列表：移除昂贵的 Count 聚合
    # Only show projects the user is actually involved in (Member/Owner/Manager)
    # 仅显示用户实际参与的项目（成员/负责人/经理）
    user_projects = Project.objects.filter(
        Q(members=request.user) | Q(owner=request.user) | Q(managers=request.user)
    ).filter(is_active=True).distinct().order_by('name')

    context = {
        'reports': page_obj,
        'page_obj': page_obj,
        'per_page': per_page,
        'start_date': start_date,
        'end_date': end_date,
        'status': status,
        'project_id': int(project_id) if project_id and project_id.isdigit() else '',
        'role': role,
        'q': q,
        'total_count': paginator.count, # Use paginator's cached count if available
        'latest_date': page_obj[0].date if page_obj else None, # Avoid extra query | 避免额外查询
        'projects': user_projects,
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
@transaction.atomic
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
    
    # 编辑优化：限制加载的项目数量
    selected_project_ids = list(report.projects.values_list('id', flat=True))
    
    # 1. 最近使用的项目
    recent_pids = list(DailyReport.projects.through.objects.filter(
        dailyreport__user=request.user
    ).order_by('-dailyreport_id').values_list('project_id', flat=True)[:50])
    
    final_pids = []
    seen = set()
    
    # Ensure selected are present
    for pid in selected_project_ids:
        if pid not in seen:
            final_pids.append(pid)
            seen.add(pid)
            
    # Add recent
    for pid in recent_pids:
        if pid not in seen:
            final_pids.append(pid)
            seen.add(pid)
            
    # Fill up to 50
    remaining = 50 - len(final_pids)
    if remaining > 0:
        others = Project.objects.filter(project_filter).exclude(id__in=seen).order_by('name').values_list('id', flat=True)[:remaining]
        final_pids.extend(others)
        
    projects_map = {p.id: p for p in Project.objects.filter(id__in=final_pids)}
    projects_list = [projects_map[pid] for pid in final_pids if pid in projects_map]

    errors = []

    if request.method == 'POST':
        return daily_report_create(request)  # reuse logic by same endpoint?  # noqa

    context = {
        'user_position': position,
        'projects': projects_list,
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
    # 统一日报视图：超级管理员查看所有，其他人仅查看可访问的
    reports, role, start_date, end_date = _filtered_reports(request)
    
    # 获取可访问项目列表（统一逻辑）
    if request.user.is_superuser:
        accessible_projects = Project.objects.filter(is_active=True)
    else:
        accessible_projects = get_accessible_projects(request.user)
    
    # 权限控制：如果不是超级管理员，仅显示其有权管理的项目的日报
    if not request.user.is_superuser:
        # 优化：使用 Exists 子查询替代 filter(...).distinct()，避免昂贵的 JOIN 和去重操作
        reports = reports.filter(
            Exists(
                DailyReport.projects.through.objects.filter(
                    dailyreport_id=OuterRef('pk'),
                    project_id__in=accessible_projects.values('id')
                )
            )
        )

    username = (request.GET.get('username') or '').strip()
    user_id = request.GET.get('user')
    project_id = request.GET.get('project')
    status = (request.GET.get('status') or '').strip()

    if username:
        # 优化：如果是 PostgreSQL，建议使用 SearchVector 进行全文检索
        # 对于 MySQL/SQLite，istartswith 比 icontains 更快（如果支持索引前缀）
        # 这里保留 icontains 兼容性，但限制在特定字段组合
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
    # 优化：使用单次查询替代三次 count() 查询
    # 清除排序以避免开销
    # 注意：如果不需要总数，可以移除 stats['total']
    stats = reports.order_by().aggregate(
        total=Count('id'),
        submitted=Count(Case(When(status='submitted', then=1), output_field=IntegerField())),
        draft=Count(Case(When(status='draft', then=1), output_field=IntegerField()))
    )
    total_count = stats['total']
    submitted_count = stats['submitted']
    draft_count = stats['draft']

    try:
        per_page = int(request.GET.get('per_page', 20))
        if per_page not in [10, 20, 50, 100]:
            per_page = 20
    except (ValueError, TypeError):
        per_page = 20

    paginator = Paginator(reports, per_page)
    # 优化：手动设置 count 以避免 Paginator 执行额外的 COUNT(*) 查询
    paginator.count = total_count
    
    page_obj = paginator.get_page(request.GET.get('page'))
    
    # 优化：获取项目列表用于筛选下拉框
    # 仅获取必要的字段，并限制数量或使用 AJAX
    # 如果项目数量巨大，建议在前端使用搜索组件，这里只返回前 100 个活跃项目
    projects = accessible_projects.order_by('name').only('id', 'name')[:100]

    log_action(request, 'access', f"admin_reports count={total_count} role={role} start={start_date} end={end_date} username={username} project={project_id} status={status}")
    context = {
        'reports': page_obj,
        'page_obj': page_obj,
        'per_page': per_page,
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
        # 'users': get_user_model().objects.order_by('username'), # Unused in template
        'status': status,
    }
    return render(request, 'reports/admin_reports.html', context)

@login_required
def daily_report_batch_create(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            reports_data = data.get('reports', [])
            
            # 安全：限制批量大小以防止 DoS
            if len(reports_data) > 50:
                 return JsonResponse({'success': False, 'message': '批量创建限制单次最多 50 条 / Max 50 reports per batch'}, status=400)

            created_count = 0
            errors = []
            
            # 获取用户的角色/职位
            try:
                role = request.user.profile.position
            except (Profile.DoesNotExist, AttributeError):
                role = 'dev'

            # 预获取现有日报以避免 N+1 查询
            dates_to_check = []
            for item in reports_data:
                d_str = item.get('date')
                if d_str:
                    try:
                        dates_to_check.append(parse_date(d_str))
                    except (ValueError, TypeError):
                        pass
            
            existing_dates = set()
            if dates_to_check:
                existing_dates = set(
                    DailyReport.objects.filter(
                        user=request.user, 
                        role=role, 
                        date__in=[d for d in dates_to_check if d]
                    ).values_list('date', flat=True)
                )

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

                if report_date in existing_dates:
                     errors.append(f"第 {index + 1} 行：{date_str} 的日报已存在")
                     continue
                
                # 创建日报
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
                    # 过滤有效的项目 ID（必须是可访问的）
                    valid_projects = get_accessible_projects(request.user).filter(id__in=project_ids)
                    report.projects.set(valid_projects)
                
                created_count += 1
            
            if errors:
                return JsonResponse({'success': False, 'message': '部分日报创建失败', 'errors': errors, 'created_count': created_count})
            
            return JsonResponse({'success': True, 'message': f'成功创建 {created_count} 份日报'})

        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)
