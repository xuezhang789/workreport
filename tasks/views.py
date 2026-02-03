import json
import re
import os
import logging
from datetime import datetime, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse, Http404
from django.utils.http import url_has_allowed_host_and_scheme
from django.db.models import Q, Count, Avg, F
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.core.paginator import Paginator
from django.contrib import messages
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.urls import reverse

from projects.models import Project
from tasks.models import Task, TaskAttachment, TaskComment
from core.constants import TaskStatus, TaskCategory
from tasks.services.state import TaskStateService
from audit.utils import log_action
from audit.models import AuditLog, TaskHistory
from audit.services import AuditLogService
from core.models import Profile, SystemSetting, ExportJob
from work_logs.models import DailyReport
from core.utils import (
    _admin_forbidden,
    _friendly_forbidden,
    _validate_file,
    _stream_csv,
    _create_export_job,
    _generate_export_file
)
from tasks.services.sla import (
    calculate_sla_info, 
    get_sla_hours, 
    get_sla_thresholds,
    _ensure_sla_timer,
    _get_sla_timer_readonly
)
from tasks.services.export import TaskExportService
from reports.utils import get_accessible_projects, can_manage_project, get_manageable_projects
from reports.signals import _invalidate_stats_cache

logger = logging.getLogger(__name__)

MAX_EXPORT_ROWS = 5000
EXPORT_CHUNK_SIZE = 500
MENTION_PATTERN = re.compile(r'@([\w.@+-]+)')
MANAGER_ROLES = {'mgr', 'pm'}
DEFAULT_SLA_REMIND = getattr(settings, 'SLA_REMIND_HOURS', 24)

def has_manage_permission(user):
    # 已弃用：请使用 can_manage_project(user, project) 进行更细粒度的控制。
    # 为了兼容旧代码保留，但默认返回 False 以强制显式检查。
    return False

def _add_history(task: Task, user, field: str, old: str, new: str):
    # 已弃用：audit/signals.py 中的信号通过 pre_save/post_save 自动处理审计日志创建。
    pass

@login_required
def admin_task_list(request):
    # 统一任务列表：超级管理员查看所有，其他用户查看有权限项目中的任务
    accessible_projects = get_accessible_projects(request.user)
    if not request.user.is_superuser and not accessible_projects.exists():
        return _admin_forbidden(request, "需要相关项目权限 / Project access required")

    status = (request.GET.get('status') or '').strip()
    category = (request.GET.get('category') or '').strip()
    priority = (request.GET.get('priority') or '').strip()
    project_id = request.GET.get('project')
    user_id = request.GET.get('user')
    q = (request.GET.get('q') or '').strip()
    hot = request.GET.get('hot') == '1'
    sort_by = request.GET.get('sort', '-created_at')

    tasks_qs = Task.objects.select_related('project', 'user', 'sla_timer').prefetch_related('collaborators')
    
    # 预取一次 SLA 设置
    cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
    sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
    
    cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
    sla_thresholds_val = cfg_thresholds.value if cfg_thresholds else None
    
    now = timezone.now()
    # 如果没有指定项目，则使用默认 SLA 小时数进行通用查询
    default_sla_hours = get_sla_hours(system_setting_value=sla_hours_val)
    
    due_soon_ids = set(tasks_qs.filter(
        status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW],
        due_at__gt=now,
        due_at__lte=now + timedelta(hours=default_sla_hours)
    ).values_list('id', flat=True))
    
    if not request.user.is_superuser:
        tasks_qs = tasks_qs.filter(project__in=accessible_projects)
    if status in dict(Task.STATUS_CHOICES):
        tasks_qs = tasks_qs.filter(status=status)
    if category in dict(Task.CATEGORY_CHOICES):
        tasks_qs = tasks_qs.filter(category=category)
    if priority in dict(Task.PRIORITY_CHOICES):
        tasks_qs = tasks_qs.filter(priority=priority)
    if project_id and project_id.isdigit():
        pid = int(project_id)
        if request.user.is_superuser or accessible_projects.filter(id=pid).exists():
            tasks_qs = tasks_qs.filter(project_id=pid)
        else:
            tasks_qs = tasks_qs.none()
    if user_id and user_id.isdigit():
        tasks_qs = tasks_qs.filter(user_id=int(user_id))
    if q:
        tasks_qs = tasks_qs.filter(Q(title__icontains=q) | Q(content__icontains=q))

    if hot:
        # 优化：在数据库层面过滤以减少内存使用
        # 'hot' 意味着 '逾期' 或 '紧急' (剩余时间 < amber_threshold)
        # 调整后的截止时间 = due_at + total_paused_seconds
        # 条件: adjusted_due < cutoff_time
        # 因为 paused_seconds >= 0, 所以 adjusted_due >= due_at.
        # 如果 adjusted_due < cutoff_time, 那么 due_at < cutoff_time.
        # 我们可以安全地通过 due_at < cutoff_time 过滤得到一个超集，
        # 避免在某些数据库上导致问题的复杂 DB 运算 (ExpressionWrapper)。
        
        amber_hours = get_sla_thresholds(sla_thresholds_val).get('amber', 4)
        cutoff_time = now + timedelta(hours=amber_hours)
        
        hot_qs = tasks_qs.exclude(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]).filter(
            due_at__isnull=False,
            due_at__lt=cutoff_time
        )
        
        # 回退到 Python 进行精确的状态计算和排序，但基于一个小得多的数据集
        tasks = list(hot_qs)
        
        # 使用 Python 逻辑再次检查以确保与 calculate_sla_info 一致
        tasks = [t for t in tasks if calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)['status'] in ('tight', 'overdue')]
        
        far_future = now + timedelta(days=365)
        for t in tasks:
            t.is_due_soon = t.id in due_soon_ids
            t.sla_info = calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)
        tasks.sort(key=lambda t: (
            -t.created_at.timestamp(),
            t.sla_info.get('sort', 3),
            t.sla_info.get('remaining_hours') if t.sla_info.get('remaining_hours') is not None else 9999,
            t.due_at or far_future,
        ))
        paginator = Paginator(tasks, 15)
        page_obj = paginator.get_page(request.GET.get('page'))
    else:
        # 标准排序
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
        tasks_qs = tasks_qs.order_by(sort_field)

        # 标准视图的数据库分页（性能优化）
        paginator = Paginator(tasks_qs, 15)
        page_obj = paginator.get_page(request.GET.get('page'))
        for t in page_obj:
            t.is_due_soon = t.id in due_soon_ids
            t.sla_info = calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)

    User = get_user_model()
    if request.user.is_superuser:
        user_objs = User.objects.all().order_by('username')
        project_choices = Project.objects.filter(is_active=True).order_by('name')
    else:
        project_choices = accessible_projects.order_by('name')
        # 可访问项目中的用户
        user_objs = User.objects.filter(
            Q(project_memberships__in=accessible_projects) |
            Q(managed_projects__in=accessible_projects) |
            Q(owned_projects__in=accessible_projects)
        ).distinct().order_by('username')
    return render(request, 'tasks/admin_task_list.html', {
        'tasks': page_obj,
        'page_obj': page_obj,
        'status': status,
        'category': category,
        'priority': priority,
        'q': q,
        'project_id': int(project_id) if project_id and project_id.isdigit() else '',
        'user_id': int(user_id) if user_id and user_id.isdigit() else '',
        'hot': hot,
        'sort_by': sort_by,
        'projects': project_choices,
        'users': user_objs,
        'task_status_choices': Task.STATUS_CHOICES,
        'task_category_choices': Task.CATEGORY_CHOICES,
        'task_priority_choices': Task.PRIORITY_CHOICES,
        'due_soon_ids': due_soon_ids,
        'sla_config_hours': default_sla_hours,
        'redirect_to': request.get_full_path(),
        'sla_thresholds': get_sla_thresholds(system_setting_value=sla_thresholds_val),
    })


@login_required
def admin_task_bulk_action(request):
    manageable_project_ids = set(Project.objects.filter(managers=request.user, is_active=True).values_list('id', flat=True))
    is_admin = request.user.is_superuser
    if not is_admin and not manageable_project_ids:
        return _admin_forbidden(request, "需要管理员或项目管理员权限 / Admin or project manager required")
    if request.method != 'POST':
        return _admin_forbidden(request, "仅允许 POST / POST only")
    ids = request.POST.getlist('task_ids')
    action = request.POST.get('action')  # Fixed param name
    redirect_to = request.POST.get('redirect_to')
    if redirect_to and not url_has_allowed_host_and_scheme(url=redirect_to, allowed_hosts={request.get_host()}):
        redirect_to = None
    
    # 过滤上下文用于记录日志
    project_id = request.POST.get('project')
    user_id = request.POST.get('user')

    total_requested = len(ids)
    tasks = Task.objects.filter(id__in=ids)
    if not is_admin:
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
                # _add_history 已移除
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
                # _add_history 已移除
                t.due_at = parsed_due
                update_fields.append('due_at')
            if assign_user and assign_user.id != t.user_id and (is_admin or t.project_id in manageable_project_ids):
                # _add_history 已移除
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
    manageable_project_ids = set(Project.objects.filter(managers=request.user, is_active=True).values_list('id', flat=True))
    is_admin = request.user.is_superuser
    if not is_admin and not manageable_project_ids:
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
    
    if not is_admin:
        tasks = tasks.filter(project_id__in=manageable_project_ids)
    if status in dict(Task.STATUS_CHOICES):
        tasks = tasks.filter(status=status)
    if priority in dict(Task.PRIORITY_CHOICES):
        tasks = tasks.filter(priority=priority)
    if project_id and project_id.isdigit():
        pid = int(project_id)
        if is_admin or pid in manageable_project_ids:
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
        for t in tasks.iterator(chunk_size=EXPORT_CHUNK_SIZE):
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
            path = _generate_export_file(
                job,
                TaskExportService.get_header(),
                TaskExportService.get_export_rows(tasks if isinstance(tasks, list) else tasks.iterator(chunk_size=EXPORT_CHUNK_SIZE))
            )
            return JsonResponse({'queued': True, 'job_id': job.id})
        except Exception as e:
            job.status = 'failed'
            job.message = str(e)
            job.save(update_fields=['status', 'message', 'updated_at'])
            return JsonResponse({'error': 'export failed'}, status=500)

    rows = TaskExportService.get_export_rows(tasks if isinstance(tasks, list) else tasks.iterator(chunk_size=EXPORT_CHUNK_SIZE))
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
        except Exception:
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
    if not request.user.is_superuser and not accessible_projects.exists():
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
    
    if not request.user.is_superuser:
        base_tasks = base_tasks.filter(project__in=accessible_projects)
        base_reports = base_reports.filter(projects__in=accessible_projects)

    # 应用非日期过滤器
    project_id = request.GET.get('project')
    user_id = request.GET.get('user')
    role = request.GET.get('role')
    q = (request.GET.get('q') or '').strip()

    if project_id and project_id.isdigit():
        pid = int(project_id)
        if request.user.is_superuser or accessible_projects.filter(id=pid).exists():
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
    # 显示最近 14/30 天，无论过滤器如何？或者匹配过滤器？
    # 如果选择 "本月"，显示该月的每日趋势。
    # 如果 "本周"，显示本周每日。
    # 如果 "今天"，也许每小时？（目前太复杂）。
    # 默认为：如果范围 < 60 天，每日。否则每周/每月。
    
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
    # 对于分布，通常如果没有日期范围，我们看 *当前活跃* 任务，
    # 或者 *范围期间创建* 的任务。
    # "任务统计" 通常暗示 "在此期间产生的任务状态如何？"
    # 如果设置了期间，让我们按范围内的 `created_at` 过滤。
    dist_qs = base_tasks
    if start_date and end_date:
        dist_qs = dist_qs.filter(created_at__date__range=(start_date, end_date))
        
    status_dist = list(dist_qs.values('status').annotate(c=Count('id')).order_by('-c'))
    status_map = dict(Task.STATUS_CHOICES)
    priority_dist = list(dist_qs.values('priority').annotate(c=Count('id')))
    priority_map = dict(Task.PRIORITY_CHOICES)

    # --- 6. 缺失日报 (可操作) ---
    # 逻辑同前，但仅针对 "今天"
    missing_count = 0
    
    if period == 'today' or period == 'custom': # 仅在相关时显示缺失
        # ... (Missing logic reused from previous) ...
        # 优化：仅在需要时计算
        # Optimization: Use 'date' field instead of 'created_at__date' for index usage
        reported_ids = DailyReport.objects.filter(date=today).values_list('user_id', flat=True)
        
        # 相关用户
        target_projs = Project.objects.filter(is_active=True)
        if not request.user.is_superuser:
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
        
        # 缺失项目分组 (如果 count > 0)
        if missing_count > 0:
             # ... (重用分组逻辑) ...
             # 为简洁起见，在此重构中简化
             pass

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
            'new': metric_new,
            'new_growth': growth_new,
            'new_growth_abs': abs(growth_new),
            'done': metric_done,
            'done_growth': growth_done,
            'done_growth_abs': abs(growth_done),
            'rate': rate_throughput,
            'rate_growth': growth_rate, 
            'rate_growth_abs': abs(growth_rate),
            'overdue': metric_overdue,
            'missing_reports': missing_count,
            'on_time_rate': rate_on_time,
            'on_time_growth': growth_on_time,
            'on_time_growth_abs': abs(growth_on_time),
            'avg_time': round(metric_avg_time, 1),
            'avg_time_growth': growth_avg_time,
            'avg_time_growth_abs': abs(growth_avg_time),
        },
        
        # Charts
        'trend': {
            'labels': trend_labels,
            'created': trend_created,
            'completed': trend_completed,
        },
        'dist': {
            'status': [{'label': status_map.get(x['status'], x['status']), 'value': x['c'], 'code': x['status']} for x in status_dist],
            'priority': [{'label': priority_map.get(x['priority'], x['priority']), 'value': x['c'], 'code': x['priority']} for x in priority_dist],
        },
        
        # Tables
        'projects_data': project_stats,
        'users_data': user_stats,
        
        # Filters
        'projects': Project.objects.filter(is_active=True).order_by('name') if request.user.is_superuser else accessible_projects,
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
    if not request.user.is_superuser and not accessible_projects.exists():
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
    if not request.user.is_superuser:
        tasks = tasks.filter(project__in=accessible_projects)
    if project_id and project_id.isdigit():
        pid = int(project_id)
        if request.user.is_superuser or accessible_projects.filter(id=pid).exists():
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
    if not user.is_superuser and not accessible_projects.exists():
        return _admin_forbidden(request, "您没有权限创建任务 / No accessible projects")

    projects_qs = Project.objects.filter(is_active=True)
    if not user.is_superuser:
        # 筛选下拉菜单的项目：仅显示用户可以管理的项目
        # 因为普通成员不能创建任务。
        manageable_projects = get_manageable_projects(user)
        projects_qs = projects_qs.filter(id__in=manageable_projects.values('id'))
        
    projects = projects_qs.annotate(task_count=Count('tasks')).order_by('-task_count', 'name')
    User = get_user_model()
    # 性能优化：不要加载所有用户。
    # user_objs = list(User.objects.all().order_by('username'))
    existing_urls = [u for u in Task.objects.exclude(url='').values_list('url', flat=True).distinct()]

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
        elif not request.user.is_superuser:
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
    
    can_see = user.is_superuser or \
              get_accessible_projects(user).filter(id=task.project.id).exists() or \
              task.user == user or \
              task.collaborators.filter(pk=user.pk).exists()
              
    if not can_see:
        raise Http404
            
    # 检查权限（超级用户，项目拥有者/管理者，任务拥有者，或协作者）
    # 注意：普通成员可以编辑他们自己的任务或如果他们是协作者。
    # 但他们不能编辑与他们无关的任务，即使是在同一个项目中。
    can_manage = user.is_superuser or \
                 can_manage_project(user, task.project) or \
                 task.user == user or \
                 task.collaborators.filter(pk=user.pk).exists()
                 
    if not can_manage:
        return _admin_forbidden(request)

    # 权限检查：仅限协作者的限制
    can_full_edit = user.is_superuser or \
                    can_manage_project(user, task.project) or \
                    task.user == user
    is_collaborator_only = not can_full_edit and task.collaborators.filter(pk=user.pk).exists()

    projects_qs = Project.objects.filter(is_active=True)
    if not user.is_superuser:
        # 简化：显示可访问的项目，但在保存时验证。
        accessible_projects = get_accessible_projects(user)
        projects_qs = projects_qs.filter(id__in=accessible_projects.values('id'))
        
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
            elif not user.is_superuser:
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

@login_required
def task_upload_attachment(request, task_id):
    task = get_object_or_404(Task, pk=task_id)
    
    # 权限检查
    # 超级用户，项目拥有者/管理者，任务拥有者，或协作者
    can_upload = request.user.is_superuser or \
                 can_manage_project(request.user, task.project) or \
                 task.user == request.user or \
                 task.collaborators.filter(pk=request.user.pk).exists()
    
    if not can_upload:
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)
    
    if request.method == 'POST' and request.FILES.getlist('files'):
        uploaded_files = []
        for file in request.FILES.getlist('files'):
            is_valid, error_msg = _validate_file(file)
            if not is_valid:
                return JsonResponse({'status': 'error', 'message': error_msg}, status=400)
                
            attachment = TaskAttachment.objects.create(
                task=task,
                user=request.user,
                file=file
            )
            uploaded_files.append({
                'id': attachment.id,
                'name': file.name,
                'size': file.size,
                'url': attachment.file.url,
                'uploaded_by': attachment.user.get_full_name() or attachment.user.username,
                'created_at': attachment.created_at.strftime('%Y-%m-%d %H:%M')
            })
            
        return JsonResponse({'status': 'success', 'files': uploaded_files})
        
    return JsonResponse({'status': 'error', 'message': 'No files provided'}, status=400)

@login_required
def task_delete_attachment(request, attachment_id):
    attachment = get_object_or_404(TaskAttachment, pk=attachment_id)
    task = attachment.task
    
    # 权限检查
    # 超级用户，任务负责人 (Assigned To)，或上传者
    can_delete = request.user.is_superuser or \
                 task.user == request.user or \
                 attachment.user == request.user
    
    if not can_delete:
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)
        
    if request.method == 'POST':
        attachment.delete()
        return JsonResponse({'status': 'success'})
        
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

@login_required
def api_task_detail(request, pk: int):
    """用于编辑表单的获取任务详情的 API。"""
    task = get_object_or_404(Task, pk=pk)
    
    # 权限检查 (重用 admin_task_edit 的逻辑)
    can_see = request.user.is_superuser or \
              get_accessible_projects(request.user).filter(id=task.project.id).exists() or \
              task.user == request.user or \
              task.collaborators.filter(pk=request.user.pk).exists()
              
    if not can_see:
        return JsonResponse({'error': 'Not Found'}, status=404)
        
    return JsonResponse({
        'id': task.id,
        'title': task.title,
        'url': task.url,
        'content': task.content,
        'project_id': task.project_id,
        'user_id': task.user_id,
        'category': task.category,
        'status': task.status,
        'priority': task.priority,
        'due_at': task.due_at.isoformat() if task.due_at else '',
        'collaborator_ids': list(task.collaborators.values_list('id', flat=True)),
    })

@login_required
def task_list(request):
    """面向用户的任务列表，带有筛选和完成按钮。"""
    status = (request.GET.get('status') or '').strip()
    category = (request.GET.get('category') or '').strip()
    project_id = request.GET.get('project')
    q = (request.GET.get('q') or '').strip()
    hot = request.GET.get('hot') == '1'
    priority = (request.GET.get('priority') or '').strip()

    # 优化查询，使用select_related和prefetch_related减少数据库查询
    # 添加 user__preferences 以避免头像显示时的 N+1 查询
    tasks_qs = Task.objects.select_related(
        'project', 'user', 'sla_timer', 'user__preferences'
    ).prefetch_related(
        'collaborators'
    )

    # Permission check: Show tasks from accessible projects
    if not request.user.is_superuser:
        # 现：可访问项目中的所有任务
        accessible_projects = get_accessible_projects(request.user)
        tasks_qs = tasks_qs.filter(project__in=accessible_projects)
    
    # 优化：移除不必要的 distinct() 调用，它会显著增加查询开销
    tasks_qs = tasks_qs.order_by('-created_at')
    
    now = timezone.now()
    
    project_obj = None
    if project_id and project_id.isdigit():
        project_obj = Project.objects.filter(id=int(project_id)).first()
    
    # 预取SLA设置，避免在循环中重复查询
    cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
    sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
    
    cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
    # 修复：正确解析阈值配置为字典，避免传给 calculate_sla_info 时出错
    sla_thresholds_val = get_sla_thresholds(cfg_thresholds.value if cfg_thresholds else None)
    
    sla_hours = get_sla_hours(system_setting_value=sla_hours_val)
    
    # 优化：使用 count() 替代获取所有 ID，避免大量数据加载
    due_soon_filter = Q(
        status__in=['todo', 'in_progress', 'blocked', 'in_review'],
        due_at__gt=now,
        due_at__lte=now + timedelta(hours=sla_hours)
    )
    due_soon_count = tasks_qs.filter(due_soon_filter).count()

    # 应用过滤器
    if status:
        tasks_qs = tasks_qs.filter(status=status)
    if category in dict(Task.CATEGORY_CHOICES):
        tasks_qs = tasks_qs.filter(category=category)
    if project_id and project_id.isdigit():
        tasks_qs = tasks_qs.filter(project_id=project_id)
    if q:
        tasks_qs = tasks_qs.filter(title__icontains=q)
    if priority in dict(Task.PRIORITY_CHOICES):
        tasks_qs = tasks_qs.filter(priority=priority)

    if hot:  # 显示即将到期的任务
        tasks_qs = tasks_qs.filter(due_soon_filter)

    # 排序处理
    sort_by = request.GET.get('sort', '-created_at')

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
    
    # 如果是按优先级排序，因为优先级是文本字段且有特定顺序(high, medium, low)，
    # 简单的字母排序可能不符合预期。通常建议使用 Case/When，但这里为简化保持字段排序。
    # 实际项目中建议在 Model 定义 Integer choices 或使用 Case/When 排序。
    # 这里保持简单字段排序。
    tasks_qs = tasks_qs.order_by(sort_field)

    # 分页
    paginator = Paginator(tasks_qs, 20)
    page_number = request.GET.get('page')
    tasks = paginator.get_page(page_number)

    # 批量计算SLA信息，避免在模板中逐个计算
    for task in tasks:
        task.sla_info = calculate_sla_info(task, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)

    # 获取项目列表用于筛选
    projects = Project.objects.filter(is_active=True)
    if not request.user.is_superuser:
        accessible_projects = get_accessible_projects(request.user)
        projects = projects.filter(id__in=accessible_projects.values('id'))
    
    projects = projects.order_by('name')

    return render(request, 'tasks/task_list.html', {
        'tasks': tasks,
        'projects': projects,
        'selected_status': status,
        'selected_category': category,
        'selected_project_id': int(project_id) if project_id and project_id.isdigit() else None,
        'q': q,
        'hot': hot,
        'priority': priority,
        'priorities': Task.PRIORITY_CHOICES,
        'task_category_choices': Task.CATEGORY_CHOICES,
        'due_soon_count': due_soon_count,
        'sort_by': sort_by,
    })


@login_required
def task_export(request):
    """导出当前筛选的我的任务列表。"""
    status = (request.GET.get('status') or '').strip()
    priority = (request.GET.get('priority') or '').strip()
    project_id = request.GET.get('project')
    q = (request.GET.get('q') or '').strip()
    hot = request.GET.get('hot') == '1'

    tasks = Task.objects.select_related('project', 'user', 'user__profile', 'sla_timer').prefetch_related('collaborators')
    
    if not request.user.is_superuser:
        accessible_projects = get_accessible_projects(request.user)
        tasks = tasks.filter(project__in=accessible_projects)
    
    tasks = tasks.distinct().order_by('-created_at')
    
    if status in dict(Task.STATUS_CHOICES):
        tasks = tasks.filter(status=status)
    if priority in dict(Task.PRIORITY_CHOICES):
        tasks = tasks.filter(priority=priority)
    if project_id and project_id.isdigit():
        tasks = tasks.filter(project_id=int(project_id))
    if q:
        tasks = tasks.filter(Q(title__icontains=q) | Q(content__icontains=q))
    if hot:
        filtered = []
        # Pre-fetch SLA settings once
        cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
        sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
        cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
        sla_thresholds_val = cfg_thresholds.value if cfg_thresholds else None

        # 使用 list() 替代 iterator() 以支持 prefetch_related
        for t in tasks:
            info = calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)
            if info['status'] in ('tight', 'overdue'):
                t.sla_info = info
                filtered.append(t)
        tasks = filtered
    total_count = len(tasks) if isinstance(tasks, list) else tasks.count()
    if total_count > MAX_EXPORT_ROWS:
        if request.GET.get('queue') != '1':
            return HttpResponse("数据量过大，请缩小筛选范围后再导出 / Data too large, please narrow filters. 如需排队导出，请带 queue=1 参数 / Use queue=1 to enqueue export.", status=400)
        # 走异步导出队列（简化为后台生成 + 轮询）
        job = _create_export_job(request.user, 'my_tasks')
        try:
            path = _generate_export_file(
                job,
                TaskExportService.get_header(),
                TaskExportService.get_export_rows(tasks if isinstance(tasks, list) else list(tasks))
            )
            return JsonResponse({'queued': True, 'job_id': job.id})
        except Exception as e:
            job.status = 'failed'
            job.message = str(e)
            job.save(update_fields=['status', 'message', 'updated_at'])
            return JsonResponse({'error': 'export failed'}, status=500)

    rows = TaskExportService.get_export_rows(tasks if isinstance(tasks, list) else list(tasks))
    header = TaskExportService.get_header()
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename=\"tasks.csv\"'
    log_action(request, 'export', f"tasks count={total_count} q={q}")
    return response


@login_required
def task_export_selected(request):
    """导出选中的任务（我的任务）。"""
    if request.method != 'POST':
        return _admin_forbidden(request, "仅允许 POST / POST only")
    ids = request.POST.getlist('task_ids')
    tasks = Task.objects.select_related('project', 'user').prefetch_related('collaborators').filter(user=request.user, id__in=ids)
    # _mark_overdue_tasks(tasks) - 已弃用逻辑
    if not tasks.exists():
        return HttpResponse("请选择任务后导出", status=400)
    rows = TaskExportService.get_export_rows(tasks.iterator(chunk_size=EXPORT_CHUNK_SIZE))
    header = TaskExportService.get_header()
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename=\"tasks_selected.csv\"'
    log_action(request, 'export', f"tasks_selected count={tasks.count()}")
    return response


@login_required
def task_complete(request, pk: int):
    task = get_object_or_404(Task, pk=pk)
    
    # 权限检查：用户所有者，协作者，或项目管理员
    if not (task.user == request.user or 
            task.collaborators.filter(pk=request.user.pk).exists() or 
            can_manage_project(request.user, task.project)):
        return _friendly_forbidden(request, "无权限完成该任务 / No permission to complete this task")

    if request.method != 'POST':
        return _friendly_forbidden(request, "仅允许 POST / POST only")
    # 完成任务
    try:
        with transaction.atomic():
            # _add_history 已移除
            task.status = 'done'
            task.completed_at = timezone.now()
            timer = _get_sla_timer_readonly(task)
            if timer and timer.paused_at:
                timer.total_paused_seconds += int((timezone.now() - timer.paused_at).total_seconds())
                timer.paused_at = None
                timer.save(update_fields=['total_paused_seconds', 'paused_at'])
            task.save(update_fields=['status', 'completed_at'])
        log_action(request, 'update', f"task_complete {task.id}")
        messages.success(request, "任务已标记完成 / Task marked as completed.")
    except Exception as exc:
        logger.error(f"Failed to complete task {task.id}: {exc}", exc_info=True)
        messages.error(request, f"任务完成失败，请重试 / Failed to complete task: {exc}")
    
    next_url = request.GET.get('next') or request.POST.get('next')
    if next_url and url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('tasks:task_list')


@login_required
def task_bulk_action(request):
    if request.method != 'POST':
        return _admin_forbidden(request, "仅允许 POST / POST only")
    ids = request.POST.getlist('task_ids')
    action = request.POST.get('bulk_action')
    redirect_to = request.POST.get('redirect_to')
    if redirect_to and not url_has_allowed_host_and_scheme(url=redirect_to, allowed_hosts={request.get_host()}):
        redirect_to = None
        
    # 权限：拥有者，协作者，或项目管理员
    manageable_projects = get_manageable_projects(request.user)
    
    tasks = Task.objects.filter(
        Q(user=request.user) | 
        Q(collaborators=request.user) |
        Q(project__in=manageable_projects)
    ).filter(id__in=ids).distinct()
    
    skipped_perm = max(0, len(ids) - tasks.count())
    total_selected = tasks.count()
    updated = 0
    if action == 'complete':
        now = timezone.now()
        audit_batch = []
        for t in tasks:
            audit_batch.append(AuditLog(
                user=request.user,
                operator_name=request.user.get_full_name(),
                action='update',
                target_type='Task',
                target_id=str(t.id),
                target_label=str(t)[:255],
                details={'diff': {'status': {'old': t.status, 'new': 'done'}}},
                project=t.project,
                task=t,
                result='success'
            ))
        AuditLog.objects.bulk_create(audit_batch)
        tasks.update(status='done', completed_at=now)
        updated = total_selected
        log_action(request, 'update', f"task_bulk_complete count={tasks.count()}")
    elif action == 'reopen':
        audit_batch = []
        for t in tasks:
            audit_batch.append(AuditLog(
                user=request.user,
                operator_name=request.user.get_full_name(),
                action='update',
                target_type='Task',
                target_id=str(t.id),
                target_label=str(t)[:255],
                details={'diff': {'status': {'old': t.status, 'new': 'todo'}}},
                project=t.project,
                task=t,
                result='success'
            ))
        AuditLog.objects.bulk_create(audit_batch)
        tasks.update(status='todo', completed_at=None)
        updated = total_selected
        log_action(request, 'update', f"task_bulk_reopen count={tasks.count()}")
    elif action == 'delete':
        if not request.user.is_superuser:
            return _admin_forbidden(request, "仅超级管理员可批量删除 / Superuser only")
        count = tasks.count()
        
        # 删除审计日志
        audit_batch = []
        for t in tasks:
            audit_batch.append(AuditLog(
                user=request.user,
                operator_name=request.user.get_full_name(),
                action='delete',
                target_type='Task',
                target_id=str(t.id),
                target_label=str(t)[:255],
                details={'reason': 'bulk_delete'},
                project=t.project,
                result='success'
            ))
        AuditLog.objects.bulk_create(audit_batch)
        
        tasks.delete()
        updated = count
        log_action(request, 'delete', f"task_bulk_delete count={count}")
    elif action == 'update':
        status_value = (request.POST.get('status_value') or '').strip()
        due_at_str = (request.POST.get('due_at') or '').strip()
        parsed_due = None
        if due_at_str:
            try:
                parsed = datetime.fromisoformat(due_at_str)
                parsed_due = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
            except ValueError:
                messages.error(request, "截止时间格式不正确 / Invalid due date format")
                return redirect(redirect_to or 'tasks:task_list')
        valid_status = status_value in dict(Task.STATUS_CHOICES)
        updated = 0
        now = timezone.now()
        for t in tasks:
            update_fields = []
            if valid_status and status_value != t.status:
                # _add_history 已移除
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
                # _add_history 已移除
                t.due_at = parsed_due
                update_fields.append('due_at')
            if update_fields:
                t.save(update_fields=update_fields)
                updated += 1
        if updated:
            log_action(request, 'update', f"task_bulk_update status={status_value or '-'} due_at={'yes' if parsed_due else 'no'} count={updated}")
    if skipped_perm:
        messages.warning(request, f"{skipped_perm} 条因无权限未处理")
    if updated:
        messages.success(request, f"批量操作完成：更新 {updated}/{total_selected} 条")
    else:
        messages.info(request, "未更新任何任务，请检查操作与选择")
    
    # log_action 是手动业务日志，AuditLog 是自动数据日志。
    # 我们保留 log_action 用于高级 "批量动作" 跟踪。
    log_action(
        request,
        'update',
        f"task_bulk_action {action or '-'} updated={updated} total={total_selected} skipped_perm={skipped_perm}",
        data={'action': action, 'updated': updated, 'total': total_selected, 'skipped_perm': skipped_perm},
    )
    _invalidate_stats_cache()
    return redirect(redirect_to or 'tasks:task_list')


@login_required
def task_view(request, pk: int):
    """View task content or redirect to URL."""
    # 使用 prefetch_related 获取协作者以避免访问时的 N+1 查询
    task = get_object_or_404(Task.objects.select_related('project', 'user').prefetch_related('collaborators'), pk=pk)
    
    # 权限检查
    can_manage = can_manage_project(request.user, task.project)
    is_owner = task.user == request.user
    is_collab = task.collaborators.filter(pk=request.user.pk).exists()
    is_member = task.project.members.filter(pk=request.user.pk).exists()
    
    # 可见性：管理者（包括超级用户），拥有者，协作者，和项目成员
    if not (can_manage or is_owner or is_collab or is_member):
         return _friendly_forbidden(request, "无权限查看此任务 / No permission to view this task")
         
    can_edit = can_manage or is_owner or is_collab


    if request.method == 'POST' and 'action' in request.POST:
        if request.POST.get('action') == 'add_comment':
            comment_text = (request.POST.get('comment') or '').strip()
            if comment_text:
                # 记录任务评论，便于协作
                mentions = []
                usernames = set(MENTION_PATTERN.findall(comment_text))
                if usernames:
                    User = get_user_model()
                    mention_users = list(User.objects.filter(username__in=usernames))
                    mentions = [u.username for u in mention_users]
                TaskComment.objects.create(task=task, user=request.user, content=comment_text, mentions=mentions)
                log_action(request, 'create', f"task_comment {task.id}")
        elif request.POST.get('action') == 'reopen' and task.status in ('done', 'closed'):
            # 已完成任务支持重新打开
            # _add_history 已移除
            task.status = 'todo'
            task.completed_at = None
            task.save(update_fields=['status', 'completed_at'])
            log_action(request, 'update', f"task_reopen {task.id}")
        elif request.POST.get('action') == 'pause_timer':
            timer = _ensure_sla_timer(task)
            if not timer.paused_at:
                timer.paused_at = timezone.now()
                timer.save(update_fields=['paused_at'])
                if task.status != 'blocked':
                    # _add_history 已移除
                    task.status = 'blocked'
                    task.save(update_fields=['status'])
                messages.success(request, "计时已暂停")
                log_action(request, 'update', f"task_pause {task.id}")
        elif request.POST.get('action') == 'resume_timer':
            timer = _ensure_sla_timer(task)
            if timer.paused_at:
                timer.total_paused_seconds += int((timezone.now() - timer.paused_at).total_seconds())
                timer.paused_at = None
                timer.save(update_fields=['total_paused_seconds', 'paused_at'])
                if task.status == 'blocked':
                    # _add_history 已移除
                    task.status = 'in_progress'
                    task.save(update_fields=['status'])
                messages.success(request, "计时已恢复")
                log_action(request, 'update', f"task_resume {task.id}")
        elif request.POST.get('action') == 'add_attachment':
            attach_url = (request.POST.get('attachment_url') or '').strip()
            attach_file = request.FILES.get('attachment_file')
            if attach_file:
                is_valid, error_msg = _validate_file(attach_file)
                if not is_valid:
                    messages.error(request, error_msg)
                    log_action(request, 'update', f"task_attachment_reject {task.id}")
                else:
                    TaskAttachment.objects.create(task=task, user=request.user, url=attach_url, file=attach_file)
                    messages.success(request, "附件已上传")
                    log_action(request, 'create', f"task_attachment {task.id}")
            elif attach_url:
                TaskAttachment.objects.create(task=task, user=request.user, url=attach_url, file=None)
                messages.success(request, "附件链接已添加")
                log_action(request, 'create', f"task_attachment {task.id}")
        elif request.POST.get('action') == 'set_status':
            new_status = request.POST.get('status_value')
            
            # 验证流转
            if not TaskStateService.validate_transition(task.category, task.status, new_status):
                 messages.error(request, f"无效的状态流转：无法从 {task.get_status_display()} 变更为 {dict(Task.STATUS_CHOICES).get(new_status, new_status)}")
                 return redirect('tasks:task_view', pk=pk)

            if new_status in dict(Task.STATUS_CHOICES):
                try:
                    with transaction.atomic():
                        # _add_history 已移除，因为 AuditLog 信号会处理它
                        if new_status in ('done', 'closed'):
                            task.status = new_status
                            task.completed_at = timezone.now()
                            timer = _get_sla_timer_readonly(task)
                            if timer and timer.paused_at:
                                timer.total_paused_seconds += int((timezone.now() - timer.paused_at).total_seconds())
                                timer.paused_at = None
                                timer.save(update_fields=['total_paused_seconds', 'paused_at'])
                        else:
                            task.status = new_status
                            if task.completed_at:
                                task.completed_at = None
                        task.save(update_fields=['status', 'completed_at'])
                    
                    # BUG 状态通知
                    if task.category == TaskCategory.BUG:
                        if new_status == TaskStatus.VERIFYING:
                            # 通知测试人员 (项目 QA)
                            # 注意：任务负责人已由通用 'notify_task_assignment' 信号通知
                            qas = list(task.project.members.filter(profile__position='qa'))
                            for qa_user in qas:
                                if qa_user != request.user and qa_user != task.user:
                                    send_notification(
                                        user=qa_user,
                                        title="缺陷待验证 / Bug Ready for Verification",
                                        message=f"缺陷 {task.title} 已修复，请进行验证",
                                        notification_type='task_updated',
                                        priority='high',
                                        data={'task_id': task.id, 'project_id': task.project.id}
                                    )
                            
                        # CLOSED 状态通知由通用的 Owner/Collaborators 信号处理

                    log_action(request, 'update', f"task_status {task.id} -> {new_status}")
                    messages.success(request, "状态已更新 / Status updated.")
                except Exception as exc:
                    logger.error(f"Failed to update status for task {task.id}: {exc}", exc_info=True)
                    messages.error(request, f"状态更新失败，请重试 / Failed to update status: {exc}")
        return redirect('tasks:task_view', pk=pk)

    log_action(request, 'access', f"task_view {task.id}")
    comments = task.comments.select_related('user').all()
    attachments = task.attachments.select_related('user').all()
    
    # 统一历史记录 (Task 的 AuditLogs) 已从此移除，移至单独视图
    
    sla_ref_time = task.completed_at if task.completed_at else None
    
    allowed_statuses = TaskStateService.get_allowed_next_statuses(task.category, task.status)
    
    return render(request, 'tasks/task_detail.html', {
        'task': task,
        'comments': comments,
        'attachments': attachments,
        'sla': calculate_sla_info(task, as_of=sla_ref_time),
        'can_edit': can_edit,
        'allowed_statuses': allowed_statuses,
        'task_status_choices': Task.STATUS_CHOICES, # 用于映射的完整选项
    })


@login_required
def task_history(request, pk: int):
    task = get_object_or_404(Task, pk=pk)
    
    # 权限检查 (同 task_view)
    can_view = (
        request.user.is_superuser or 
        request.user == task.user or 
        task.project.members.filter(id=request.user.id).exists() or
        task.project.managers.filter(id=request.user.id).exists() or
        task.project.owner == request.user or
        task.collaborators.filter(id=request.user.id).exists()
    )
    
    if not can_view:
        return _friendly_forbidden(request, "无权查看该任务历史 / No permission to view task history")

    # Filters
    filters = {
        'user_id': request.GET.get('user'),
        'start_date': request.GET.get('start_date'),
        'end_date': request.GET.get('end_date'),
        'action_type': request.GET.get('action_type'), # field_change, attachment, comment
        'field_name': request.GET.get('field'),
        'q': request.GET.get('q'),
    }

    qs = AuditLogService.get_history(task, filters)
    
    # Pagination
    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Format logs for display
    timeline = []
    for log in page_obj:
        entry = AuditLogService.format_log_entry(log, filters.get('field_name'))
        if entry:
            timeline.append(entry)

    # AJAX / HTMX support for lazy loading
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'audit/timeline.html', {'logs': timeline})
    
    # Get users for filter - Optimization: Only fetch users who have history in this task
    # 获取用于筛选的用户 - 优化：仅获取在此任务中有历史记录的用户
    log_user_ids = AuditLog.objects.filter(
        target_type='Task', 
        target_id=str(task.id)
    ).values_list('user_id', flat=True).distinct()
    
    users = get_user_model().objects.filter(id__in=log_user_ids).order_by('username')

    return render(request, 'tasks/task_history.html', {
        'task': task, 
        'logs': timeline,
        'page_obj': page_obj,
        'filters': filters,
        'users': users
    })
    
    # Pagination
    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Format logs for display
    timeline = []
    for log in page_obj:
        entry = AuditLogService.format_log_entry(log, filters.get('field_name'))
        if entry:
            timeline.append(entry)
    
    # Get users for filter
    users = get_user_model().objects.filter(
        Q(pk=task.user_id) | 
        Q(project_memberships=task.project) | 
        Q(collaborated_tasks=task)
    ).distinct()

    return render(request, 'tasks/task_history.html', {
        'task': task, 
        'logs': timeline,
        'page_obj': page_obj,
        'filters': filters,
        'users': users
    })
