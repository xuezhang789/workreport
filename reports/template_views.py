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
from core.utils import _admin_forbidden, has_manage_permission
from audit.utils import log_action
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
    all_roles_dict = dict(Profile.ROLE_CHOICES)
    if role_filter not in all_roles_dict:
        role_filter = 'dev'

    # Handle POST (Save)
    if request.method == 'POST':
        role = request.POST.get('role')
        if role != role_filter:
             # Should not happen if UI is correct, but safety check
             pass
        
        hint = request.POST.get('hint', '').strip()
        sample_md = request.POST.get('sample_md', '').strip()
        placeholders_raw = request.POST.get('placeholders', '{}')
        
        # Handle sort_order safely
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
    if not request.user.is_superuser:
        return _admin_forbidden(request)

    tab = request.GET.get('tab', 'report')  # 'report' or 'task'
    
    # Handle Create/Edit Form Submission
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
    
    # Report Templates
    latest_report_versions = ReportTemplateVersion.objects.filter(
        version=Subquery(
            ReportTemplateVersion.objects.filter(name=OuterRef('name'))
            .order_by('-version')
            .values('version')[:1]
        )
    ).order_by('-created_at')
    
    # Task Templates
    latest_task_versions = TaskTemplateVersion.objects.filter(
        version=Subquery(
            TaskTemplateVersion.objects.filter(name=OuterRef('name'))
            .order_by('-version')
            .values('version')[:1]
        )
    ).order_by('-created_at')

    # Filter by search
    q = request.GET.get('q')
    if q:
        latest_report_versions = latest_report_versions.filter(Q(name__icontains=q) | Q(description__icontains=q))
        latest_task_versions = latest_task_versions.filter(Q(name__icontains=q) | Q(description__icontains=q))

    # Pagination
    paginator_report = Paginator(latest_report_versions, 10)
    page_report = paginator_report.get_page(request.GET.get('page'))
    
    paginator_task = Paginator(latest_task_versions, 10)
    page_task = paginator_task.get_page(request.GET.get('page')) # Note: sharing page param for tabs is imperfect but simple

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
            qs = ReportTemplateVersion.objects.filter(role=role) # is_active=True?
            if project_id:
                match = qs.filter(project_id=project_id).order_by('-version').first()
            if not match:
                match = qs.filter(project__isnull=True, is_shared=True).order_by('-version').first()
    
    elif tpl_type == 'task':
        if tpl_id:
            match = get_object_or_404(TaskTemplateVersion, id=tpl_id)
    
    if match:
        return JsonResponse({
            'success': True, 
            'content': match.content,
            'placeholders': getattr(match, 'placeholders', {}),
            'fallback': True if not tpl_id else False
        })
    else:
        # No template found, return empty or default
        return JsonResponse({'success': False, 'message': 'No template found', 'content': {}})
        
@login_required
@require_http_methods(["GET"])
def template_recommend_api(request):
    """
    Recommend templates based on context (e.g., project type, user role).
    """
    tpl_type = request.GET.get('type', 'report')
    q = request.GET.get('q', '')
    
    if tpl_type == 'report':
        qs = ReportTemplateVersion.objects.filter() # is_active?
        if q:
            qs = qs.filter(name__icontains=q)
        # Simple recommendation: return top 5 latest
        data = list(qs.order_by('-created_at')[:5].values('id', 'name', 'description'))
    else:
        qs = TaskTemplateVersion.objects.filter()
        if q:
            qs = qs.filter(name__icontains=q)
        data = list(qs.order_by('-created_at')[:5].values('id', 'name', 'description'))
        
    return JsonResponse({'success': True, 'templates': data})
