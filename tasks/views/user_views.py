import json
import logging
import re
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
from tasks.models import Task, TaskAttachment, TaskTemplateVersion, TaskComment
from core.constants import TaskStatus, TaskCategory
from audit.utils import log_action
from audit.models import AuditLog
from audit.services import AuditLogService
from core.models import Profile, SystemSetting, ChunkedUpload
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
from tasks.services.state import TaskStateService
from reports.utils import get_accessible_projects, can_manage_project, get_manageable_projects
from reports.signals import _invalidate_stats_cache
from reports.services.notification_service import send_notification
from core.services.upload_service import UploadService

logger = logging.getLogger(__name__)

MAX_EXPORT_ROWS = 5000
EXPORT_CHUNK_SIZE = 500
MENTION_PATTERN = re.compile(r'@([\w.@+-]+)')

@login_required
def task_upload_attachment(request, task_id):
    task = get_object_or_404(Task, pk=task_id)
    
    # 权限检查
    # 超级用户，项目拥有者/管理者，任务拥有者，或协作者
    can_upload = can_manage_project(request.user, task.project) or \
                 task.user == request.user or \
                 task.collaborators.filter(pk=request.user.pk).exists()
    
    if not can_upload:
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)
    
    if request.method == 'POST':
        uploaded_files = []
        
        # 1. Handle Chunked Upload Completion (via upload_id)
        if request.POST.get('upload_id'):
            upload_id = request.POST.get('upload_id')
            try:
                # Verify ownership
                chunk_upload = ChunkedUpload.objects.get(id=upload_id)
                if chunk_upload.user != request.user:
                    return JsonResponse({'status': 'error', 'message': 'Permission denied for this upload'}, status=403)
                
                # Finalize
                content_file, error = UploadService.complete_chunked_upload(upload_id)
                if error:
                    return JsonResponse({'status': 'error', 'message': error}, status=400)
                
                # Create Attachment
                attachment = TaskAttachment.objects.create(
                    task=task,
                    user=request.user,
                    file=content_file 
                )
                
                uploaded_files.append({
                    'id': attachment.id,
                    'name': attachment.file.name,
                    'size': attachment.file.size,
                    'url': attachment.file.url,
                    'uploaded_by': attachment.user.get_full_name() or attachment.user.username,
                    'created_at': attachment.created_at.strftime('%Y-%m-%d %H:%M')
                })
                
            except ChunkedUpload.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'Upload session not found'}, status=404)
            except Exception as e:
                return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

        # 2. Handle Standard File Upload (via FILES)
        elif request.FILES.getlist('files'):
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
                    'name': attachment.file.name,
                    'size': attachment.file.size,
                    'url': attachment.file.url,
                    'uploaded_by': attachment.user.get_full_name() or attachment.user.username,
                    'created_at': attachment.created_at.strftime('%Y-%m-%d %H:%M')
                })
            
        if uploaded_files:
            return JsonResponse({'status': 'success', 'files': uploaded_files})
        
    return JsonResponse({'status': 'error', 'message': 'No files provided'}, status=400)

@login_required
def task_delete_attachment(request, attachment_id):
    attachment = get_object_or_404(TaskAttachment, pk=attachment_id)
    task = attachment.task
    
    # 权限检查
    # 超级用户，任务负责人 (Assigned To)，或上传者 (if still has access)
    can_delete = can_manage_project(request.user, task.project) or \
                 task.user == request.user or \
                 attachment.user == request.user
    
    if not can_delete:
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)
        
    if request.method == 'POST':
        attachment.delete()
        return JsonResponse({'status': 'success'})
        
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

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
    # 优化：添加 user__profile 到 select_related
    tasks_qs = Task.objects.select_related(
        'project', 'user', 'sla_timer', 'user__preferences', 'user__profile'
    ).prefetch_related(
        'collaborators', 'collaborators__profile'
    )

    # 权限检查：显示可访问项目的任务
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
    
    tasks_qs = tasks_qs.order_by(sort_field)

    # 分页
    try:
        per_page = int(request.GET.get('per_page', 20))
        if per_page not in [10, 20, 50, 100]:
            per_page = 20
    except (ValueError, TypeError):
        per_page = 20

    paginator = Paginator(tasks_qs, per_page)
    page_number = request.GET.get('page')
    tasks = paginator.get_page(page_number)

    # 批量计算SLA信息，避免在模板中逐个计算
    for task in tasks:
        task.sla_info = calculate_sla_info(task, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)

    # 获取项目列表用于筛选
    projects = Project.objects.filter(is_active=True)
    projects = projects.filter(id__in=accessible_projects.values('id'))
    
    # 优化：仅获取 ID 和名称
    projects = projects.order_by('name').only('id', 'name')

    context = {
        'tasks': tasks,
        'page_obj': tasks, # 为了与其他视图保持一致的别名
        'per_page': per_page,
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
    }

    if request.headers.get('HX-Request'):
         return render(request, 'tasks/partials/task_list_content.html', context)

    return render(request, 'tasks/task_list.html', context)


@login_required
def task_export(request):
    """导出当前筛选的我的任务列表。"""
    status = (request.GET.get('status') or '').strip()
    priority = (request.GET.get('priority') or '').strip()
    project_id = request.GET.get('project')
    q = (request.GET.get('q') or '').strip()
    hot = request.GET.get('hot') == '1'

    tasks = Task.objects.select_related('project', 'user', 'user__profile', 'sla_timer').prefetch_related('collaborators')
    
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
        
        # Trigger progress update
        for pid in tasks.values_list('project_id', flat=True).distinct():
            Project.objects.get(id=pid).update_progress()
            
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
        
        # Trigger progress update
        for pid in tasks.values_list('project_id', flat=True).distinct():
            Project.objects.get(id=pid).update_progress()
            
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
        
        # Store project IDs before delete
        project_ids = list(tasks.values_list('project_id', flat=True).distinct())
        
        tasks.delete()
        
        # Trigger progress update
        for pid in project_ids:
            Project.objects.get(id=pid).update_progress()
            
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
    # 优化：预取所有相关数据以最小化数据库查询
    task_qs = Task.objects.select_related(
        'project', 
        'user', 
        'user__profile',  # 用于用户头像/职位
        'project__owner', # 用于权限检查
        'sla_timer'       # 用于 SLA 计算
    ).prefetch_related(
        'collaborators',
        'collaborators__profile', # 用于协作者头像
        'collaborators__preferences', # 用于协作者头像 (user.preferences)
        'attachments',
        'attachments__user',
        'comments',
        'comments__user',
        'comments__user__profile', # 用于评论作者头像
        'comments__user__preferences' # 用于评论作者头像
    )
    
    task = get_object_or_404(task_qs, pk=pk)
    
    # 权限检查
    can_manage = can_manage_project(request.user, task.project)
    is_owner = task.user == request.user
    is_collab = task.collaborators.filter(pk=request.user.pk).exists()
    
    # 检查用户是否为项目成员（通过 RBAC）
    # 使用 accessible_projects 检查等同于检查他们是否拥有 project.view
    is_member = get_accessible_projects(request.user).filter(pk=task.project.id).exists()
    
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
                messages.success(request, "评论已发布 / Comment posted")
        
        elif request.POST.get('action') == 'reopen' and task.status in ('done', 'closed'):
            # 已完成任务支持重新打开
            task.status = 'todo'
            if task.category == TaskCategory.BUG:
                task.status = TaskStatus.NEW
                
            task.completed_at = None
            task.save(update_fields=['status', 'completed_at'])
            log_action(request, 'update', f"task_reopen {task.id}")
            messages.success(request, "任务已重新打开 / Task reopened")
            
        elif request.POST.get('action') == 'pause_timer':
            timer = _ensure_sla_timer(task)
            if not timer.paused_at:
                timer.paused_at = timezone.now()
                timer.save(update_fields=['paused_at'])
                if task.status != 'blocked':
                    task.status = 'blocked'
                    task.save(update_fields=['status'])
                messages.success(request, "计时已暂停 / Timer paused")
                log_action(request, 'update', f"task_pause {task.id}")
                
        elif request.POST.get('action') == 'resume_timer':
            timer = _ensure_sla_timer(task)
            if timer.paused_at:
                timer.total_paused_seconds += int((timezone.now() - timer.paused_at).total_seconds())
                timer.paused_at = None
                timer.save(update_fields=['total_paused_seconds', 'paused_at'])
                if task.status == 'blocked':
                    task.status = 'in_progress'
                    task.save(update_fields=['status'])
                messages.success(request, "计时已恢复 / Timer resumed")
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
                    messages.success(request, "附件已上传 / Attachment uploaded")
                    log_action(request, 'create', f"task_attachment {task.id}")
            elif attach_url:
                TaskAttachment.objects.create(task=task, user=request.user, url=attach_url, file=None)
                messages.success(request, "附件链接已添加 / Attachment link added")
                log_action(request, 'create', f"task_attachment {task.id}")
                
        elif request.POST.get('action') == 'set_status':
            new_status = request.POST.get('status_value')
            is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json'
            
            # 验证流转
            if not TaskStateService.validate_transition(task.category, task.status, new_status):
                 msg = f"无效的状态流转：无法从 {task.get_status_display()} 变更为 {dict(Task.STATUS_CHOICES).get(new_status, new_status)}"
                 if is_ajax:
                     return JsonResponse({'status': 'error', 'message': msg}, status=400)
                 messages.error(request, msg)
                 return redirect('tasks:task_view', pk=pk)

            if new_status in dict(Task.STATUS_CHOICES):
                try:
                    with transaction.atomic():
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
                    
                    log_action(request, 'update', f"task_status {task.id} -> {new_status}")
                    
                    if is_ajax:
                        return JsonResponse({'status': 'success', 'message': '状态已更新 / Status updated'})
                    messages.success(request, "状态已更新 / Status updated")
                except Exception as exc:
                    msg = f"状态更新失败，请重试 / Failed to update status: {exc}"
                    if is_ajax:
                        return JsonResponse({'status': 'error', 'message': msg}, status=500)
                    messages.error(request, msg)
        
        return redirect('tasks:task_view', pk=pk)

    # 在 prefetch 中预计算
    comments = task.comments.all() 
    attachments = task.attachments.all()
    
    sla_ref_time = task.completed_at if task.completed_at else None
    
    allowed_statuses = TaskStateService.get_allowed_next_statuses(task.category, task.status)
    category_statuses = TaskStateService.get_all_statuses_for_category(task.category)
    
    # 构建用于模板的状态选项列表 [(value, label), ...]
    status_choices = []
    full_choices = dict(Task.STATUS_CHOICES)
    for s in category_statuses:
        if s in full_choices:
            status_choices.append((s, full_choices[s]))
    
    return render(request, 'tasks/task_detail.html', {
        'task': task,
        'comments': comments,
        'attachments': attachments,
        'sla': calculate_sla_info(task, as_of=sla_ref_time),
        'can_edit': can_edit,
        'allowed_statuses': allowed_statuses,
        'status_choices': status_choices, # 替换原来的 task_status_choices
    })


@login_required
def task_history(request, pk: int):
    task = get_object_or_404(Task, pk=pk)
    
    # 权限检查 (同 task_view)
    can_view = (
        get_accessible_projects(request.user).filter(id=task.project.id).exists() or
        task.user == request.user or 
        task.collaborators.filter(id=request.user.id).exists()
    )
    
    if not can_view:
        return _friendly_forbidden(request, "无权查看该任务历史 / No permission to view task history")

    # 过滤器
    filters = {
        'user_id': request.GET.get('user'),
        'start_date': request.GET.get('start_date'),
        'end_date': request.GET.get('end_date'),
        'action_type': request.GET.get('action_type'), # field_change, attachment, comment
        'field_name': request.GET.get('field'),
        'q': request.GET.get('q'),
    }

    qs = AuditLogService.get_history(task, filters)
    
    # 分页
    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # 格式化日志以进行显示
    timeline = []
    for log in page_obj:
        entry = AuditLogService.format_log_entry(log, filters.get('field_name'))
        if entry:
            timeline.append(entry)

    # AJAX / HTMX 支持懒加载
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'audit/timeline.html', {'logs': timeline})
    
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
