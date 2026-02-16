from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count, OuterRef, Subquery
import json

from work_logs.models import RoleTemplate, ReportTemplateVersion
from tasks.models import TaskTemplateVersion
from core.models import Profile
from reports.forms import ReportTemplateForm
from tasks.forms import TaskTemplateForm
from core.utils import _admin_forbidden
from core.permissions import has_manage_permission
from audit.utils import log_action
from audit.models import AuditLog
from reports.signals import _invalidate_stats_cache

ROLE_FIELDS_MAPPING = {
    'dev': ['today_work', 'progress_issues', 'tomorrow_plan'],
    'qa': ['testing_scope', 'testing_progress', 'bug_summary', 'testing_tomorrow'],
    'pm': ['product_today', 'product_coordination', 'product_tomorrow'],
    'ui': ['ui_today', 'ui_feedback', 'ui_tomorrow'],
    'ops': ['ops_today', 'ops_monitoring', 'ops_tomorrow'],
    'mgr': ['mgr_progress', 'mgr_risks', 'mgr_tomorrow'],
}

@login_required
def role_template_manage(request):
    """
    Manage role templates for daily reports.
    Now supports filtering by role to switch between templates without overwriting context.
    """
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)

    role_filter = (request.GET.get('role') or 'dev').strip()
    
    # Validate role
    # 验证角色
    all_roles_dict = dict(Profile.ROLE_CHOICES)
    if role_filter not in all_roles_dict:
        role_filter = 'dev'

    # Handle POST (Save)
    # 处理 POST (保存)
    if request.method == 'POST':
        role = request.POST.get('role')
        if role != role_filter:
             # Should not happen if UI is correct, but safety check
             # 如果 UI 正确，不应发生，但作为安全检查
             pass
        
        hint = request.POST.get('hint', '').strip()
        sample_md = request.POST.get('sample_md', '').strip()
        placeholders_raw = request.POST.get('placeholders', '{}')
        
        # Handle sort_order safely
        # 安全处理 sort_order
        try:
            sort_order = int(request.POST.get('sort_order') or 0)
        except (ValueError, TypeError):
            sort_order = 0
            
        is_active = request.POST.get('is_active') == 'on'
        
        try:
            placeholders = json.loads(placeholders_raw)
        except json.JSONDecodeError:
            messages.error(request, "JSON 格式错误 / Invalid JSON format")
            placeholders = {}

        # Update or Create
        # 更新或创建
        obj, created = RoleTemplate.objects.update_or_create(
            role=role_filter,
            defaults={
                'hint': hint,
                'sample_md': sample_md,
                'placeholders': placeholders,
                'sort_order': sort_order,
                'is_active': is_active
            }
        )
        
        log_action(
            user=request.user,
            action='CREATE' if created else 'UPDATE',
            target_model='RoleTemplate',
            target_object_id=obj.id,
            message=f"{'Created' if created else 'Updated'} role template for {all_roles_dict[role_filter]}"
        )
        
        _invalidate_stats_cache(role=role_filter)
        messages.success(request, f"模版已保存 / Template saved ({all_roles_dict[role_filter]})")
        return redirect(f"{request.path}?role={role_filter}")

    # GET: Get existing template or default
    # GET: 获取现有模板或默认值
    try:
        tpl = RoleTemplate.objects.get(role=role_filter)
        hint_text = tpl.hint
        sample_text = tpl.sample_md
        placeholders_text = json.dumps(tpl.placeholders, indent=4, ensure_ascii=False)
        is_active = tpl.is_active
        sort_order_value = tpl.sort_order
        updated_at = tpl.updated_at
    except RoleTemplate.DoesNotExist:
        hint_text = ""
        sample_text = ""
        placeholders_text = "{}"
        is_active = True
        sort_order_value = 0
        updated_at = None

    context = {
        'roles': Profile.ROLE_CHOICES,
        'selected_role': role_filter,
        'hint_text': hint_text,
        'sample_text': sample_text,
        'placeholders_text': placeholders_text,
        'is_active': is_active,
        'sort_order_value': sort_order_value,
        'updated_at': updated_at,
        'current_fields': ROLE_FIELDS_MAPPING.get(role_filter, []),
    }
    return render(request, 'reports/role_template_manage.html', context)


@login_required
@require_http_methods(["GET"])
def role_template_api(request):
    """
    API to get template content for a specific role.
    Used by frontend to populate daily report form.
    """
    role = request.GET.get('role')
    if not role:
        return JsonResponse({'error': 'Role required'}, status=400)
    
    # 1. Try to find system default for this role
    # 1. 尝试查找此角色的系统默认值
    try:
        tpl = RoleTemplate.objects.get(role=role, is_active=True)
        return JsonResponse({
            'hint': tpl.hint,
            'placeholders': tpl.placeholders,
            'sample_md': tpl.sample_md
        })
    except RoleTemplate.DoesNotExist:
        pass
    
    # 2. Fallback default placeholders if no DB template
    # 2. 如果没有数据库模板，则回退到默认占位符
    defaults = {
        'dev': {'today_work': '', 'progress_issues': '', 'tomorrow_plan': ''},
        'qa': {'testing_scope': '', 'testing_progress': '', 'bug_summary': '', 'testing_tomorrow': ''},
        'pm': {'product_today': '', 'product_coordination': '', 'product_tomorrow': ''},
        'ui': {'ui_today': '', 'ui_feedback': '', 'ui_tomorrow': ''},
        'ops': {'ops_today': '', 'ops_monitoring': '', 'ops_tomorrow': ''},
        'mgr': {'mgr_progress': '', 'mgr_risks': '', 'mgr_tomorrow': ''},
    }
    return JsonResponse({
        'hint': '', 
        'placeholders': defaults.get(role, {}),
        'sample_md': ''
    })


@login_required
def template_center(request):
    """
    Unified Template Center for Report and Task templates.
    """
    # Permission check (strict for center view as it implies management)
    # 权限检查（对于中心视图严格，因为它意味着管理）
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)

    tab = request.GET.get('tab', 'report')  # 'report' or 'task'
    
    # Handle Create/Edit Form Submission
    # 处理创建/编辑表单提交
    if request.method == 'POST':
        action_type = request.POST.get('type') # 'report' or 'task'
        
        if action_type == 'report':
            form = ReportTemplateForm(request.POST)
            if form.is_valid():
                tpl = form.save(commit=False)
                tpl.created_by = request.user
                tpl.save()
                messages.success(request, f"日报模板 '{tpl.name}' 已创建 (v{tpl.version})")
                return redirect(f"{request.path}?tab=report")
        elif action_type == 'task':
            form = TaskTemplateForm(request.POST)
            if form.is_valid():
                tpl = form.save(commit=False)
                tpl.created_by = request.user
                tpl.save()
                messages.success(request, f"任务模板 '{tpl.name}' 已创建 (v{tpl.version})")
                return redirect(f"{request.path}?tab=task")
        
        messages.error(request, "创建失败，请检查表单 / Creation failed, check form.")
    
    # Querysets for list view (Latest versions only logic?)
    # Requirement: "show unique templates" -> Group by name, take latest version.
    # 列表视图的查询集（仅最新版本的逻辑？）
    # 需求：“显示唯一模板”-> 按名称分组，取最新版本。
    
    # Report Templates
    # 报告模板
    latest_report_versions = ReportTemplateVersion.objects.filter(
        version=Subquery(
            ReportTemplateVersion.objects.filter(name=OuterRef('name'))
            .order_by('-version')
            .values('version')[:1]
        )
    ).order_by('-created_at')
    
    # Task Templates
    # 任务模板
    latest_task_versions = TaskTemplateVersion.objects.filter(
        version=Subquery(
            TaskTemplateVersion.objects.filter(name=OuterRef('name'))
            .order_by('-version')
            .values('version')[:1]
        )
    ).order_by('-created_at')

    # Filter by search
    # 按搜索过滤
    q = request.GET.get('q')
    if q:
        latest_report_versions = latest_report_versions.filter(Q(name__icontains=q) | Q(description__icontains=q))
        latest_task_versions = latest_task_versions.filter(Q(name__icontains=q) | Q(description__icontains=q))

    # Pagination
    # 分页
    paginator_report = Paginator(latest_report_versions, 10)
    page_report = paginator_report.get_page(request.GET.get('page'))
    
    paginator_task = Paginator(latest_task_versions, 10)
    page_task = paginator_task.get_page(request.GET.get('page')) # Note: sharing page param for tabs is imperfect but simple | 注意：为选项卡共享页面参数不完美但简单

    context = {
        'tab': tab,
        'report_templates': page_report,
        'task_templates': page_task,
        'report_form': ReportTemplateForm(),
        'task_form': TaskTemplateForm(),
        'q': q,
        'sort': request.GET.get('sort'), # For test compatibility
    }
    return render(request, 'reports/template_center.html', context)


@login_required
@require_http_methods(["GET", "POST"])
def template_apply_api(request):
    """
    Apply a template (Report or Task) to current context.
    Returns the JSON content of the template.
    Logs the usage.
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            data = request.POST
    else:
        data = request.GET

    tpl_id = data.get('id')
    tpl_type = data.get('type') # 'report' or 'task'
    role = data.get('role')
    project_id = data.get('project')
    
    match = None
    placeholders = {}

    if tpl_type == 'report':
        if tpl_id:
            match = get_object_or_404(ReportTemplateVersion, id=tpl_id)
        elif role:
            # Fallback logic: Find best match
            qs = ReportTemplateVersion.objects.filter(role=role) 
            if project_id:
                # First try project specific
                match = qs.filter(project_id=project_id).order_by('-version').first()
            if not match:
                # Then global shared
                match = qs.filter(project__isnull=True, is_shared=True).order_by('-version').first()
            if not match and not project_id:
                # If no project specified, just get any shared one for role? 
                # Or maybe RoleTemplate system default?
                # For now, let's stick to ReportTemplateVersion
                pass
    
    elif tpl_type == 'task':
        if tpl_id:
            match = get_object_or_404(TaskTemplateVersion, id=tpl_id)
        elif 'name' in data:
            name = data.get('name')
            qs = TaskTemplateVersion.objects.filter(name=name)
            if project_id:
                match = qs.filter(project_id=project_id).order_by('-version').first()
            if not match:
                match = qs.filter(project__isnull=True, is_shared=True).order_by('-version').first()
            if not match:
                match = qs.order_by('-version').first()

    if match:
        # Log Usage
        match.usage_count += 1
        match.save(update_fields=['usage_count'])
        
        # Manually create audit log since log_action util is limited
        AuditLog.objects.create(
            user=request.user,
            operator_name=request.user.get_full_name() or request.user.username,
            action='other', 
            target_type=match.__class__.__name__,
            target_id=str(match.id),
            target_label=match.name,
            project_id=project_id if project_id else (match.project_id if hasattr(match, 'project_id') else None),
            summary=f"Applied template '{match.name}' (v{match.version})",
            details={'role': role, 'project_id': project_id, 'context': 'template_apply_api'},
            result='success'
        )

        response_data = {
            'success': True, 
            'content': match.content,
            'placeholders': getattr(match, 'placeholders', {}),
            'fallback': True if not tpl_id else False,
            'id': match.id,
            'name': match.name,
            'role': match.role # Return role for frontend switching
        }
        
        if tpl_type == 'task':
            response_data.update({
                'title': match.title,
                'url': match.url,
                'project': match.project_id
            })
            
        return JsonResponse(response_data)
    else:
        # Try RoleTemplate as last resort for reports
        if tpl_type == 'report' and role:
            try:
                rt = RoleTemplate.objects.get(role=role)
                return JsonResponse({
                    'success': True,
                    'content': rt.sample_md,
                    'placeholders': rt.placeholders,
                    'fallback': True,
                    'id': f"rt_{rt.id}",
                    'name': f"Default {rt.get_role_display()} Template"
                })
            except RoleTemplate.DoesNotExist:
                pass

        return JsonResponse({'success': False, 'message': 'No template found', 'content': {}})
        
@login_required
@require_http_methods(["GET"])
def template_recommend_api(request):
    """
    Recommend templates based on context (e.g., project type, user role).
    Supports filtering and full list.
    """
    tpl_type = request.GET.get('type', 'report')
    q = request.GET.get('q', '')
    role = request.GET.get('role', '')
    project_id = request.GET.get('project', '')
    
    if tpl_type == 'report':
        qs = ReportTemplateVersion.objects.all()
        
        # 1. Filter by Role (if specified)
        if role:
            qs = qs.filter(Q(role=role) | Q(role__isnull=True) | Q(role=''))
            
        # 2. Filter by Project (Exact match or Global)
        if project_id:
            qs = qs.filter(Q(project_id=project_id) | Q(project__isnull=True))
        else:
            # If no project selected, show globals
            qs = qs.filter(project__isnull=True)
            
        # 3. Search
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(role__icontains=q))
            
        # 4. Recommendation Logic:
        # Prioritize: Same Project > Same Role > High Usage > Newest
        # Using simple ordering for now
        qs = qs.order_by('-project_id', '-usage_count', '-created_at')
        
        # Limit if needed, or pagination? For modal list we might want all relevant
        # But let's limit to 50 to avoid overload
        data = list(qs[:50].values(
            'id', 'name', 'role', 'version', 'project__name', 'usage_count', 'created_at'
        ))
        
        # Add system defaults if role is present and list is small?
        # Actually RoleTemplate is separate.
        
    else:
        qs = TaskTemplateVersion.objects.all()
        if q:
            qs = qs.filter(name__icontains=q)
        if project_id:
             qs = qs.filter(Q(project_id=project_id) | Q(project__isnull=True))
             
        data = list(qs.order_by('-usage_count', '-created_at')[:50].values(
            'id', 'name', 'description', 'version', 'project__name', 'usage_count'
        ))
        
    return JsonResponse({'success': True, 'templates': data})
