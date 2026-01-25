from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from reports.models import Profile, Project
from reports.services import teams as team_service
from reports.views import has_manage_permission, _admin_forbidden, log_action

@login_required
def teams_list(request):
    # Global Team Management is restricted to Superuser.
    # Project Managers should manage teams via Project Detail page.
    if not request.user.is_superuser:
        return _admin_forbidden(request)

    q = (request.GET.get('q') or '').strip()
    role = (request.GET.get('role') or '').strip()
    project_id = request.GET.get('project')
    
    project_filter = int(project_id) if project_id and project_id.isdigit() else None
    
    qs = team_service.get_team_members(q=q, role=role, project_id=project_filter)
    
    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'reports/teams.html', {
        'users': page_obj,
        'page_obj': page_obj,
        'q': q,
        'role': role,
        'project_filter': project_filter,
        'roles': Profile.ROLE_CHOICES,
        'total_count': qs.count(),
        'projects': Project.objects.filter(is_active=True).order_by('name'), # For modal & filter
    })

@login_required
@require_POST
def team_member_update_role(request, user_id):
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Permission denied'}, status=403)
        
    new_role = request.POST.get('role')
    success, message = team_service.update_member_role(user_id, new_role, changed_by=request.user)
    
    if success:
        messages.success(request, message)
        log_action(request, 'update', f"user_role {user_id} -> {new_role}")
    else:
        messages.error(request, message)
        
    return redirect('reports:teams')

@login_required
@require_POST
def team_member_add_project(request, user_id):
    if not has_manage_permission(request.user):
        return JsonResponse({'error': 'Permission denied'}, status=403)
        
    project_id = request.POST.get('project_id')
    if not project_id:
        messages.error(request, "Please select a project")
        return redirect('reports:teams')

    success, message = team_service.add_member_to_project(user_id, project_id, changed_by=request.user)
    
    if success:
        messages.success(request, message)
        log_action(request, 'update', f"user_project_add {user_id} -> {project_id}")
    else:
        messages.error(request, message)
        
    return redirect('reports:teams')

@login_required
@require_POST
def team_member_remove_project(request, user_id, project_id):
    if not has_manage_permission(request.user):
        return JsonResponse({'error': 'Permission denied'}, status=403)
        
    success, message = team_service.remove_member_from_project(user_id, project_id, changed_by=request.user)
    
    if success:
        messages.success(request, message)
        log_action(request, 'update', f"user_project_remove {user_id} -> {project_id}")
    else:
        messages.error(request, message)
        
    return redirect('reports:teams')
