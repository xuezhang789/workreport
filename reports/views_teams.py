from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.db import models
from reports.models import Profile, Project
from reports.services import teams as team_service
from core.utils import has_manage_permission, _admin_forbidden
from audit.utils import log_action

@login_required
def teams_list(request):
    # Permission Check: Superuser OR has 'project.manage' on at least one project
    # 权限检查：超级用户 或 在至少一个项目上拥有 'project.manage' 权限
    
    # 1. Determine Access
    if request.user.is_superuser:
        has_access = True
        manageable_projects = Project.objects.filter(is_active=True)
    else:
        # Get projects where user has 'project.manage' permission
        # Note: This relies on RBAC. If using legacy managers field, we should check that too.
        # But 'can_manage_project' usually checks RBAC.
        # However, legacy `project.managers` is also a thing.
        # Let's use `get_manageable_projects` which should ideally cover RBAC.
        # And we also need to include legacy `project.managers` and `project.owner`.
        
        from reports.utils import get_manageable_projects
        # This RBAC helper returns projects where user has 'project.manage'.
        # If RBAC is not fully migrated, we might need to combine with legacy fields.
        rbac_managed = get_manageable_projects(request.user)
        
        # Legacy/Model-field based management (Owner/Managers)
        legacy_managed = Project.objects.filter(
            models.Q(owner=request.user) | 
            models.Q(managers=request.user),
            is_active=True
        )
        
        manageable_projects = (rbac_managed | legacy_managed).distinct()
        has_access = manageable_projects.exists()

    if not has_access:
        return _admin_forbidden(request, "您没有权限管理任何团队 / You do not have permission to manage any teams")

    q = (request.GET.get('q') or '').strip()
    role = (request.GET.get('role') or '').strip()
    project_id = request.GET.get('project')
    
    project_filter = int(project_id) if project_id and project_id.isdigit() else None
    
    # Filter 'qs' (Member Directory)
    # Ideally, we should only show members who are in the projects the user can manage?
    # Or is Member Directory global? 
    # The requirement says "Project Owner... cannot view or operate other projects".
    # This implies they shouldn't see members of other projects in a way that exposes sensitive info?
    # But directory usually allows finding people to add.
    # Let's keep member directory as is for now (searchable), or filter it if strictly required.
    # Requirement: "Project Owner ... cannot access other projects".
    # This strongly suggests filtering.
    
    if request.user.is_superuser:
        qs = team_service.get_team_members(q=q, role=role, project_id=project_filter)
    else:
        # Restrict member search to manageable projects + maybe accessible projects?
        # Usually you want to add NEW members from the whole company pool.
        # So 'get_team_members' (Directory) probably needs to be ALL users so you can find them to ADD.
        # BUT 'project_teams' (The cards) MUST be filtered.
        # Let's keep Directory open (or filtered by `get_accessible_projects` if we want to be strict about visibility).
        # But for "Team Management", usually you need to see who is available.
        # Let's stick to: Directory = All Users (so you can add them).
        qs = team_service.get_team_members(q=q, role=role, project_id=project_filter)
    
    # --- Pagination for Member Directory ---
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('member_page'))

    # --- Project Team Data for "Project View" ---
    # Filtered by manageable projects
    project_teams = []
    
    # Optimization: Split queries for different purposes
    
    # 1. Lightweight query for Dropdowns (Filter & Modal)
    # No annotations needed here, just ID/Name/Code
    dropdown_projects = manageable_projects.order_by('name')
    
    # 2. Heavy query for Project List (Cards)
    # Needs member/manager counts and owner
    dashboard_projects_qs = manageable_projects.annotate(
        member_count=models.Count('members', distinct=True),
        manager_count=models.Count('managers', distinct=True)
    ).select_related('owner').order_by('name')
    
    # --- Pagination for Project Teams ---
    project_paginator = Paginator(dashboard_projects_qs, 20)
    project_page_obj = project_paginator.get_page(request.GET.get('project_page'))
    current_page_projects = project_page_obj.object_list
    
    # Optimization: Fetch role stats in bulk instead of per-project loop
    # Group by (Project, Position)
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    # Only fetch stats for projects on current page
    role_stats_qs = User.objects.filter(
        project_memberships__in=current_page_projects
    ).values(
        'project_memberships', 'profile__position'
    ).annotate(
        count=models.Count('id')
    )
    
    # Process stats in memory
    stats_map = {}
    for stat in role_stats_qs:
        p_id = stat['project_memberships']
        if not p_id: continue
        
        pos = stat['profile__position']
        cnt = stat['count']
        
        if p_id not in stats_map:
            stats_map[p_id] = []
        stats_map[p_id].append({'position': pos, 'count': cnt})
    
    for proj in current_page_projects:
        project_teams.append({
            'project': proj,
            'member_count': proj.member_count,
            'manager_count': proj.manager_count,
            'role_stats': stats_map.get(proj.id, [])
        })

    return render(request, 'reports/teams.html', {
        'users': page_obj,
        'page_obj': page_obj,
        'project_page_obj': project_page_obj,
        'q': q,
        'role': role,
        'project_filter': project_filter,
        'roles': Profile.ROLE_CHOICES,
        'total_count': qs.count(),
        'projects': dropdown_projects, # Lightweight query for dropdowns
        'project_teams': project_teams, # Processed data for cards
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
