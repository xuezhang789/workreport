from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse, Http404
from django.db.models import Q, Count, F
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.core.paginator import Paginator
from django.contrib import messages
from django.conf import settings
from django.core.mail import send_mail
from django.contrib.auth import get_user_model

from projects.models import Project, ProjectPhaseConfig, ProjectPhaseChangeLog, ProjectAttachment
from projects.forms import ProjectForm, ProjectPhaseConfigForm
from tasks.models import Task, TaskAttachment
from work_logs.models import DailyReport
from audit.models import AuditLog
from audit.utils import log_action
from audit.services import AuditLogService
from core.models import Profile
from core.constants import TaskStatus
from core.utils import (
    _admin_forbidden,
    _friendly_forbidden,
    _validate_file,
    _stream_csv,
    _throttle
)
from core.permissions import has_manage_permission, has_project_manage_permission
from reports.utils import get_accessible_projects, can_manage_project
from tasks.services.sla import calculate_sla_info
from reports.signals import _invalidate_stats_cache
from reports.services.notification_service import send_notification

MAX_EXPORT_ROWS = 5000
EXPORT_CHUNK_SIZE = 500

# has_manage_permission and has_project_manage_permission moved to core.permissions

def _filtered_projects(request):
    q = (request.GET.get('q') or '').strip()
    start_date = parse_date(request.GET.get('start_date') or '')
    end_date = parse_date(request.GET.get('end_date') or '')
    owner = (request.GET.get('owner') or '').strip()
    sort_by = request.GET.get('sort') or '-created_at'

    # Base QuerySet
    # 基础查询集
    qs = Project.objects.select_related('owner', 'owner__preferences', 'current_phase').filter(is_active=True)
    
    if not request.user.is_superuser:
        # Only Super Admin sees all.
        # Ordinary users (including PMs/Managers who are not superuser) see only accessible projects.
        # 仅超级管理员可见所有项目。
        # 普通用户（包括非超级管理员的 PM/Manager）仅可见有权限的项目。
        accessible = get_accessible_projects(request.user)
        qs = qs.filter(id__in=accessible.values('id'))

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(description__icontains=q))
    if start_date:
        qs = qs.filter(Q(start_date__gte=start_date) | Q(start_date__isnull=True))
    if end_date:
        qs = qs.filter(Q(end_date__lte=end_date) | Q(end_date__isnull=True))
    if owner:
        qs = qs.filter(Q(owner__username__icontains=owner) | Q(owner__first_name__icontains=owner) | Q(owner__last_name__icontains=owner))

    # Sorting
    if sort_by == 'name':
        qs = qs.order_by('name')
    elif sort_by == 'created_at':
        qs = qs.order_by('created_at')
    elif sort_by == 'status':
        # Active first (though filter(is_active=True) is applied above, keeping logic generic)
        qs = qs.order_by('-is_active', '-created_at') 
    elif sort_by == 'progress':
        qs = qs.order_by('-overall_progress', '-created_at')
    else:
        # Default: -created_at
        qs = qs.order_by('-created_at', '-id')

    return qs, q, start_date, end_date, owner, sort_by

import logging
logger = logging.getLogger(__name__)

def _send_phase_change_notification(project, old_phase, new_phase, changed_by):
    """
    发送项目阶段变更通知给负责人和管理员。
    Send phase change notification to project owner and admins.
    """
    subject = f"[{project.code}] 项目阶段变更通知 / Project Phase Changed"
    
    old_phase_name = old_phase.phase_name if old_phase else "N/A"
    new_phase_name = new_phase.phase_name if new_phase else "N/A"
    
    message = f"""
    项目名称 / Project: {project.name}
    变更时间 / Time: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}
    操作人 / By: {changed_by.get_full_name() or changed_by.username}
    
    阶段变更 / Phase Change:
    {old_phase_name} -> {new_phase_name}
    
    当前进度 / Current Progress: {project.overall_progress}%
    """
    
    recipients = set()
    if project.owner and project.owner.email:
        recipients.add(project.owner.email)
    
    # Add admins (superusers or managers)
    # Assuming 'managers' field on Project are also admins for this project
    for manager in project.managers.all():
        if manager.email:
            recipients.add(manager.email)
            
    # Also system admins
    for admin in get_user_model().objects.filter(is_superuser=True):
        if admin.email:
            recipients.add(admin.email)
            
    if recipients:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            list(recipients),
            fail_silently=True,
        )

@login_required
def project_list(request):
    projects, q, start_date, end_date, owner, sort_by = _filtered_projects(request)
    
    # Filter by phase
    phase_id = request.GET.get('phase')
    if phase_id and phase_id.isdigit():
        projects = projects.filter(current_phase_id=int(phase_id))
        
    # Optimization: Use annotate to count members efficiently (Avoid N+1)
    projects = projects.annotate(member_count=Count('members', distinct=True))
    
    paginator = Paginator(projects, 12)
    page_obj = paginator.get_page(request.GET.get('page'))
    
    # Optimization: Bulk fetch manageable status instead of per-project permission check
    from reports.utils import get_manageable_projects
    manageable_ids = set(
        get_manageable_projects(request.user)
        .filter(id__in=[p.id for p in page_obj])
        .values_list('id', flat=True)
    )
    
    phases = ProjectPhaseConfig.objects.filter(is_active=True)
    
    # Permission Check for Create Button
    can_create_project = request.user.is_superuser
    
    context = {
        'projects': page_obj,
        'page_obj': page_obj,
        'q': q,
        'start_date': start_date,
        'end_date': end_date,
        'owner': owner,
        'sort_by': sort_by,
        'total_count': projects.count(),
        'manageable_ids': manageable_ids,
        'phases': phases,
        'phase_id': int(phase_id) if phase_id and phase_id.isdigit() else '',
        'can_create_project': can_create_project,
    }
    return render(request, 'reports/project_list.html', context)

@login_required
def project_detail(request, pk: int):
    # Check permission first
    # 1. Superuser: All
    # 2. Others: Must be accessible (Owner/Manager/Member)
    # 首先检查权限
    # 1. 超级用户：所有权限
    # 2. 其他：必须是可访问的项目（负责人/经理/成员）
    if not request.user.is_superuser:
        accessible = get_accessible_projects(request.user)
        if not accessible.filter(pk=pk).exists():
            return _admin_forbidden(request, "您没有权限查看此项目 / You do not have permission to view this project")

    project = get_object_or_404(Project.objects.select_related('owner', 'current_phase').prefetch_related('members__profile', 'managers__profile'), pk=pk)
    
    can_manage = can_manage_project(request.user, project)
    
    recent_reports = project.reports.select_related('user').order_by('-date')[:5]
    tasks_qs = Task.objects.filter(project=project)
    
    # Optimized stats calculation
    # 优化的统计计算
    import json
    from tasks.services.sla import get_sla_hours, get_sla_thresholds
    from core.models import SystemSetting
    
    # 1. Fetch SLA settings once (Try DB, fallback to defaults)
    # We fetch raw values to pass to calculate_sla_info to avoid DB hits there
    # 1. 一次性获取 SLA 设置（尝试数据库，回退到默认值）
    # 我们获取原始值传递给 calculate_sla_info 以避免那里的数据库点击
    try:
        sla_h_setting = SystemSetting.objects.get(key='sla_hours').value
    except SystemSetting.DoesNotExist:
        sla_h_setting = None
        
    try:
        sla_t_setting = SystemSetting.objects.get(key='sla_thresholds').value
    except SystemSetting.DoesNotExist:
        sla_t_setting = None

    # 2. Aggregate counts (Cached)
    # 2. 聚合计数（缓存）
    from django.core.cache import cache
    
    stats_cache_key = f'project_stats_{pk}_{tasks_qs.count()}' # Simple invalidation by count or time
    stats = cache.get(stats_cache_key)
    
    if not stats:
        stats = tasks_qs.aggregate(
            total=Count('id'),
            completed=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])),
            overdue=Count('id', filter=Q(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW], due_at__lt=timezone.now())),
            within_sla=Count('id', filter=Q(
                status__in=[TaskStatus.DONE, TaskStatus.CLOSED],
                due_at__isnull=False,
                completed_at__isnull=False,
                completed_at__lte=F('due_at')
            ))
        )
        cache.set(stats_cache_key, stats, 300) # 5 mins
    
    total = stats['total']
    completed = stats['completed']
    overdue = stats['overdue']
    within_sla = stats['within_sla']
    sla_rate = (within_sla / completed * 100) if completed else 0
    
    # Task List Logic - Simplified for Project Detail
    # Only showing tasks for this project
    # 任务列表逻辑 - 针对项目详情进行了简化
    # 仅显示该项目的任务
    tasks_qs = Task.objects.filter(project=project).select_related('user', 'user__profile', 'sla_timer')
    
    task_status = request.GET.get('task_status')
    if task_status in dict(Task.STATUS_CHOICES):
        tasks_qs = tasks_qs.filter(status=task_status)
    elif task_status == 'active':
        tasks_qs = tasks_qs.exclude(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])
    
    task_sort = request.GET.get('task_sort')
    if task_sort == 'due_at':
        tasks_qs = tasks_qs.order_by('due_at', '-created_at')
    elif task_sort == '-due_at':
        tasks_qs = tasks_qs.order_by('-due_at', '-created_at')
    elif task_sort == 'priority':
        tasks_qs = tasks_qs.order_by('due_at') # Simple proxy for priority
    else:
        tasks_qs = tasks_qs.order_by('-created_at')

    paginator = Paginator(tasks_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Calculate SLA info for displayed tasks
    # 为显示的任务计算 SLA 信息
    for t in page_obj:
        t.sla_info = calculate_sla_info(
            t, 
            sla_hours_setting=int(sla_h_setting) if sla_h_setting else None,
            sla_thresholds_setting=json.loads(sla_t_setting) if sla_t_setting else None
        )

    phases = ProjectPhaseConfig.objects.filter(is_active=True)
    
    # New Task Creation Permission in Project Detail:
    # 1. Superuser
    # 2. Project Manager / Owner
    # (Matches 'can_manage_project')
    # 项目详情中的新建任务权限：
    # 1. 超级用户
    # 2. 项目经理 / 负责人
    # (符合 'can_manage_project')
    can_create_task = can_manage_project(request.user, project)
    
    return render(request, 'reports/project_detail.html', {
        'project': project,
        'recent_reports': recent_reports,
        'can_manage': can_manage,
        'can_create_task': can_create_task,
        'task_stats': {
            'total': total,
            'completed': completed,
            'overdue': overdue,
            'within_sla': within_sla,
            'sla_rate': sla_rate,
        },
        'phases': phases,
        'tasks': page_obj,
        'task_status': task_status,
        'task_sort': task_sort,
        'task_status_choices': Task.STATUS_CHOICES,
    })

@login_required
def project_create(request):
    if not request.user.is_superuser:
        return _admin_forbidden(request)
    
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save()
            
            # Auto-assign initial phase
            if not project.current_phase:
                initial_phase = ProjectPhaseConfig.objects.filter(is_active=True).order_by('order_index').first()
                if initial_phase:
                    project.current_phase = initial_phase
                    project.overall_progress = initial_phase.progress_percentage
                    project.save(update_fields=['current_phase', 'overall_progress'])
            
            # Handle file uploads if any (for Create mode)
            if request.FILES.getlist('files'):
                for file in request.FILES.getlist('files'):
                    is_valid, error_msg = _validate_file(file)
                    if is_valid:
                        ProjectAttachment.objects.create(
                            project=project,
                            uploaded_by=request.user,
                            file=file,
                            original_filename=file.name,
                            file_size=file.size
                        )
                        
            log_action(request, 'create', f"project {project.id} {project.code}")
            return redirect('projects:project_detail', pk=project.pk)
    else:
        form = ProjectForm()
    return render(request, 'reports/project_form.html', {'form': form, 'mode': 'create'})

@login_required
def project_edit(request, pk: int):
    project = get_object_or_404(Project, pk=pk)
    if not can_manage_project(request.user, project):
        return _admin_forbidden(request, "需要管理员权限 / Admin or project manager required")

    # Permission Logic
    is_superuser = request.user.is_superuser
    is_owner = (request.user == project.owner)
    
    # Rule 1: Only Superuser can edit Owner
    can_edit_owner = is_superuser
    
    # Rule 2: Only Superuser and Owner can edit Managers
    can_edit_managers = is_superuser or is_owner

    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project)
        
        # Enforce restrictions by disabling fields (Django ignores POST data for disabled fields)
        if not can_edit_owner:
            form.fields['owner'].disabled = True
        if not can_edit_managers:
            form.fields['managers'].disabled = True
            
        if form.is_valid():
            project = form.save()
            log_action(request, 'update', f"project {project.id} {project.code}")
            _invalidate_stats_cache()
            return redirect('projects:project_detail', pk=project.pk)
    else:
        form = ProjectForm(instance=project)
        # Set initial disabled state for UI rendering
        if not can_edit_owner:
            form.fields['owner'].disabled = True
        if not can_edit_managers:
            form.fields['managers'].disabled = True

    return render(request, 'reports/project_form.html', {
        'form': form, 
        'mode': 'edit', 
        'project': project,
        'can_edit_owner': can_edit_owner,
        'can_edit_managers': can_edit_managers
    })

@login_required
def project_delete(request, pk: int):
    project = get_object_or_404(Project, pk=pk)
    if not has_project_manage_permission(request.user, project):
        return _admin_forbidden(request, "需要管理员权限 / Admin or project manager required")
    if request.method == 'POST':
        project.is_active = False
        project.save(update_fields=['is_active'])
        log_action(request, 'delete', f"project {project.id} {project.code}")
        _invalidate_stats_cache()
        return redirect('projects:project_list')
    return render(request, 'reports/project_confirm_delete.html', {'project': project})

@login_required
def project_export(request):
    # Only superuser can export all projects.
    # Ordinary users can export accessible projects.
    # The _filtered_projects function already filters by accessible projects.
    
    projects, q, start_date, end_date, owner, _ = _filtered_projects(request)
    
    # Eager load for export loop
    projects = projects.prefetch_related('members', 'managers')

    if not (q or start_date or end_date or owner):
        return HttpResponse("请至少提供搜索关键词、负责人或日期范围后再导出。", status=400)

    if projects.count() > MAX_EXPORT_ROWS:
        return HttpResponse("数据量过大，请缩小筛选范围后再导出 / Data too large, please narrow filters.", status=400)

    rows = (
        [
            p.name,
            p.code,
            p.owner.get_full_name() or p.owner.username if p.owner else "",
            ", ".join([u.username for u in p.members.all()]),
            ", ".join([u.username for u in p.managers.all()]),
            p.start_date.isoformat() if p.start_date else "",
            p.end_date.isoformat() if p.end_date else "",
            timezone.localtime(p.created_at).strftime("%Y-%m-%d %H:%M"),
            "已停用" if not p.is_active else "启用",
        ]
        for p in projects.iterator(chunk_size=EXPORT_CHUNK_SIZE)
    )
    header = ["名称", "代码", "负责人", "成员", "管理员", "开始日期", "结束日期", "创建时间", "状态"]
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="projects.csv"'
    log_action(request, 'export', f"projects count={projects.count()} q={q} start={start_date} end={end_date} owner={owner}")
    return response

@login_required
def project_phase_config_list(request):
    if not request.user.is_superuser:
        return _admin_forbidden(request)
        
    phases = ProjectPhaseConfig.objects.all()
    form = ProjectPhaseConfigForm()
    return render(request, 'reports/project_stage_config.html', {'phases': phases, 'form': form})

@login_required
def project_phase_config_create(request):
    if not request.user.is_superuser:
        return _admin_forbidden(request)
        
    if request.method == 'POST':
        form = ProjectPhaseConfigForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "阶段创建成功 / Phase created successfully")
            return redirect('projects:project_phase_config_list')
    else:
        form = ProjectPhaseConfigForm()
        
    return render(request, 'reports/project_stage_config.html', {'form': form, 'phases': ProjectPhaseConfig.objects.all()})

@login_required
def project_phase_config_update(request, pk):
    if not request.user.is_superuser:
        return _admin_forbidden(request)
        
    phase = get_object_or_404(ProjectPhaseConfig, pk=pk)
    if request.method == 'POST':
        form = ProjectPhaseConfigForm(request.POST, instance=phase)
        if form.is_valid():
            form.save()
            messages.success(request, "阶段更新成功 / Phase updated successfully")
            return redirect('projects:project_phase_config_list')
    else:
        form = ProjectPhaseConfigForm(instance=phase)
        
    return render(request, 'reports/project_stage_config.html', {'form': form, 'phases': ProjectPhaseConfig.objects.all(), 'editing': True, 'phase_id': pk})

@login_required
def project_phase_config_delete(request, pk):
    if not request.user.is_superuser:
        return _admin_forbidden(request)
        
    phase = get_object_or_404(ProjectPhaseConfig, pk=pk)
    if request.method == 'POST':
        phase.delete()
        messages.success(request, "阶段删除成功 / Phase deleted successfully")
        return redirect('projects:project_phase_config_list')
        
    return _friendly_forbidden(request, "Invalid method")

@login_required
def project_update_phase(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    
    # Check permission: Only Project Manager or higher (and Owner/Manager of the project)
    if not can_manage_project(request.user, project):
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)
        
    if request.method == 'POST':
        phase_id = request.POST.get('phase_id')
        try:
            new_phase = ProjectPhaseConfig.objects.get(pk=phase_id)
        except ProjectPhaseConfig.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Phase not found'}, status=404)
            
        old_phase = project.current_phase
        
        if old_phase != new_phase:
            project.current_phase = new_phase
            project.overall_progress = new_phase.progress_percentage
            project.save()
            
            # Log change
            ProjectPhaseChangeLog.objects.create(
                project=project,
                old_phase=old_phase,
                new_phase=new_phase,
                old_progress=old_phase.progress_percentage if old_phase else 0,
                new_progress=new_phase.progress_percentage,
                changed_by=request.user
            )
            
            # Send notification (Best Effort)
            try:
                _send_phase_change_notification(project, old_phase, new_phase, request.user)
                
                # Notify all project members
                members = set(project.members.all())
                if project.owner:
                    members.add(project.owner)
                for manager in project.managers.all():
                    members.add(manager)
                    
                for member in members:
                    if member != request.user: # Don't notify self
                        send_notification(
                            user=member,
                            title="项目阶段变更",
                            message=f"项目 {project.name} 阶段已更新为：{new_phase.phase_name} ({new_phase.progress_percentage}%)",
                            notification_type='project_update',
                            data={'project_id': project.id}
                        )
            except Exception as e:
                # Log error but don't fail the request
                logger.error(f"Notification failed: {e}")
            
            # Note: AuditLog is automatically created via signals on project.save()
            
            return JsonResponse({
                'status': 'success', 
                'phase_name': new_phase.phase_name, 
                'progress': new_phase.progress_percentage
            })
            
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

@login_required
def project_history(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    
    if not request.user.is_superuser:
        accessible = get_accessible_projects(request.user)
        if not accessible.filter(id=project.id).exists():
             raise Http404

    # Filters
    filters = {
        'user_id': request.GET.get('user'),
        'start_date': request.GET.get('start_date'),
        'end_date': request.GET.get('end_date'),
        'action_type': request.GET.get('action_type'), # field_change, attachment, comment
        'field_name': request.GET.get('field'),
        'q': request.GET.get('q'),
    }

    qs = AuditLogService.get_history(project, filters)
    
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
    
    # Get users for filter - Optimization: Only fetch users who have history in this project
    # 获取用于筛选的用户 - 优化：仅获取在此项目中有历史记录的用户
    log_user_ids = AuditLog.objects.filter(
        target_type='Project', 
        target_id=str(project.id)
    ).values_list('user_id', flat=True).distinct()
    
    users = get_user_model().objects.filter(id__in=log_user_ids).order_by('username')

    return render(request, 'reports/project_history.html', {
        'project': project, 
        'logs': timeline,
        'page_obj': page_obj,
        'filters': filters,
        'users': users
    })

@login_required
def project_upload_attachment(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    # Check permission: Superuser or Project Member (Owner, Manager, Member)
    # Using get_accessible_projects logic or direct check
    can_upload = request.user.is_superuser or \
                 project.owner == request.user or \
                 project.managers.filter(pk=request.user.pk).exists() or \
                 project.members.filter(pk=request.user.pk).exists()
    
    if not can_upload:
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)
    
    if request.method == 'POST' and request.FILES.getlist('files'):
        uploaded_files = []
        for file in request.FILES.getlist('files'):
            is_valid, error_msg = _validate_file(file)
            if not is_valid:
                return JsonResponse({'status': 'error', 'message': error_msg}, status=400)
                
            attachment = ProjectAttachment.objects.create(
                project=project,
                uploaded_by=request.user,
                file=file,
                original_filename=file.name,
                file_size=file.size
            )
            uploaded_files.append({
                'id': attachment.id,
                'name': attachment.original_filename,
                'size': attachment.file_size,
                'url': attachment.file.url,
                'uploaded_by': attachment.uploaded_by.get_full_name() or attachment.uploaded_by.username,
                'created_at': attachment.created_at.strftime('%Y-%m-%d %H:%M')
            })
            
        return JsonResponse({'status': 'success', 'files': uploaded_files})
        
    return JsonResponse({'status': 'error', 'message': 'No files provided'}, status=400)

@login_required
def project_delete_attachment(request, attachment_id):
    attachment = get_object_or_404(ProjectAttachment, pk=attachment_id)
    project = attachment.project
    
    # Check permission
    # 1. Superuser
    # 2. Project Manager/Owner (Full Access)
    # 3. Uploader (IF they still have access to the project)
    
    has_manage = can_manage_project(request.user, project)
    is_uploader = attachment.uploaded_by == request.user
    
    # Verify project access for uploader (prevent deleted members from managing files)
    has_access = get_accessible_projects(request.user).filter(pk=project.pk).exists()
    
    can_delete = request.user.is_superuser or has_manage or (is_uploader and has_access)
                 
    if not can_delete:
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)
        
    if request.method == 'POST':
        attachment.delete()
        return JsonResponse({'status': 'success'})
        
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

@login_required
def api_project_detail(request, pk: int):
    """API to get project details for editing form."""
    project = get_object_or_404(Project, pk=pk)
    if not can_manage_project(request.user, project):
        return JsonResponse({'error': 'Forbidden'}, status=403)
        
    return JsonResponse({
        'id': project.id,
        'name': project.name,
        'code': project.code,
        'description': project.description,
        'start_date': project.start_date.isoformat() if project.start_date else '',
        'end_date': project.end_date.isoformat() if project.end_date else '',
        'sla_hours': project.sla_hours,
        'is_active': project.is_active,
        'owner_id': project.owner_id,
        'manager_ids': list(project.managers.values_list('id', flat=True)),
        'member_ids': list(project.members.values_list('id', flat=True)),
    })

@login_required
def project_search_api(request):
    """
    Project search API with advanced filtering, sorting, and optimization for large datasets.
    Supports 'lite' mode for client-side indexing.
    """
    if request.method != 'GET':
        return _friendly_forbidden(request, "仅允许 GET / GET only")
    
    # Relax throttling for search
    if _throttle(request, 'project_search_ts', min_interval=0.05):
        return JsonResponse({'error': '请求过于频繁'}, status=429)

    q = (request.GET.get('q') or '').strip()
    mode = request.GET.get('mode', 'normal') # 'normal', 'lite' (id/name/code only)
    limit = int(request.GET.get('limit', 20))
    
    user = request.user
    project_filter = Q(is_active=True)
    
    if not user.is_superuser:
        accessible_ids = get_accessible_projects(user).values_list('id', flat=True)
        project_filter &= Q(id__in=accessible_ids)

    qs = Project.objects.filter(project_filter)

    if q:
        # Pinyin match simulation: matches code (often abbr) or name
        qs = qs.filter(
            Q(name__icontains=q) | 
            Q(code__icontains=q) | 
            Q(description__icontains=q)
        )
        
        # Relevance sorting: 
        # 1. Exact Code Match
        # 2. Starts with Code
        # 3. Exact Name Match
        # 4. Starts with Name
        # 5. Others
        # This is hard to do purely in ORM efficiently for all DBs without raw SQL or CASE/WHEN.
        # For simplicity and performance, we rely on basic ordering but prioritizing 'owner' might be good.
        # User requested: "Match degree, Recent usage, Activity"
        # Since we don't have robust "Recent Usage" history in DB for all users easily accessible here without joins,
        # we'll use 'updated_at' as a proxy for activity.
        
        qs = qs.order_by('-created_at') # Proxy for activity/recent
    else:
        # Default sort: Recently created
        qs = qs.order_by('-created_at')

    if mode == 'lite':
        # Return all (or large limit) lightweight objects for client-side indexing
        # Limit to 20000 to be safe
        projects = qs.values('id', 'name', 'code')[:20000]
        data = list(projects)
        # Add simple pinyin field placeholder if we had a lib, otherwise frontend handles it.
        return JsonResponse({'results': data})

    # Normal mode: Detailed results with pagination
    projects = qs[:limit]
    data = []
    for p in projects:
        data.append({
            'id': p.id, 
            'name': p.name, 
            'code': p.code,
            'owner_name': p.owner.get_full_name() or p.owner.username if p.owner else 'N/A',
            'created_at': p.created_at.isoformat(),
        })
        
    return JsonResponse({'results': data})
