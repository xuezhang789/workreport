from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.db import models
from core.models import Profile
from projects.models import Project
from reports.services import teams as team_service
from core.utils import _admin_forbidden
from core.permissions import has_manage_permission
from core.services.preferences import resolve_page_size
from audit.utils import log_action
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from reports.utils import get_manageable_projects


def _serialize_project(project):
    return {
        'id': project.id,
        'name': project.name,
        'code': project.code,
        'overall_progress': float(project.overall_progress),
    }


def _member_project_payload(operator, target_user):
    manageable_projects = get_manageable_projects(operator).order_by('name')
    assigned_projects = list(manageable_projects.filter(members=target_user))
    assigned_ids = [project.id for project in assigned_projects]
    available_projects = manageable_projects.exclude(pk__in=assigned_ids)
    return {
        'projects': [_serialize_project(project) for project in assigned_projects],
        'available_projects': [_serialize_project(project) for project in available_projects],
    }


def _team_json_error(message, status):
    return JsonResponse({'status': 'error', 'message': message}, status=status)


@login_required
def teams_list(request):
    # 权限检查：超级用户 或 在至少一个项目上拥有 'project.manage' 权限
    
    # 1. 确定访问权限
    if request.user.is_superuser:
        has_access = True
        manageable_projects = Project.objects.filter(is_active=True)
    else:
        # 获取用户拥有 'project.manage' 权限的项目
        # 注意：这依赖于 RBAC。如果使用旧的 managers 字段，我们也应该检查。
        # 但 'can_manage_project' 通常检查 RBAC。
        # 然而，旧的 `project.managers` 也是一回事。
        # 让我们使用 `get_manageable_projects`，理想情况下它应该涵盖 RBAC。
        # 我们还需要包括旧的 `project.managers` 和 `project.owner`。
        
        # 此 RBAC 助手返回用户拥有 'project.manage' 权限的项目。
        # 它还包括基于模型字段的管理（所有者/经理）。
        manageable_projects = get_manageable_projects(request.user)
        has_access = manageable_projects.exists()

    if not has_access:
        return _admin_forbidden(request, "您没有权限管理任何团队 / You do not have permission to manage any teams")

    q = (request.GET.get('q') or '').strip()
    role = (request.GET.get('role') or '').strip()
    project_id = request.GET.get('project')
    
    project_filter = int(project_id) if project_id and project_id.isdigit() else None
    
    # 成员目录保持全员可搜索，但项目标签与项目操作只暴露可管理范围。
    if project_filter and not manageable_projects.filter(pk=project_filter).exists():
        return _admin_forbidden(request, "您无权查看该项目 / You cannot access this project")

    qs = team_service.get_team_members(
        q=q,
        role=role,
        project_id=project_filter,
        visible_projects=manageable_projects,
    )
    
    # --- 成员目录分页 ---
    member_per_page = resolve_page_size(request, request.GET, key='member_per_page')

    paginator = Paginator(qs, member_per_page)
    page_obj = paginator.get_page(request.GET.get('member_page'))

    # --- “项目视图”的项目团队数据 ---
    # 按可管理项目过滤
    project_teams = []
    
    # 优化：为不同目的拆分查询
    
    # 1. 下拉菜单的轻量级查询（过滤和模态框）
    # 这里不需要注释，只需要 ID/Name/Code
    dropdown_projects = manageable_projects.values('id', 'name', 'code').order_by('name')
    
    # 2. 项目列表（卡片）的重型查询
    # 需要成员/经理计数和所有者
    dashboard_projects_qs = manageable_projects.annotate(
        member_count=models.Count('members', distinct=True),
        manager_count=models.Count('managers', distinct=True)
    ).select_related('owner').order_by('name')
    
    # --- 项目团队分页 ---
    project_per_page = resolve_page_size(request, request.GET, key='project_per_page')

    project_paginator = Paginator(dashboard_projects_qs, project_per_page)
    project_page_obj = project_paginator.get_page(request.GET.get('project_page'))
    current_page_projects = project_page_obj.object_list
    
    # 优化：批量获取角色统计信息，而不是每个项目循环
    # 按 (Project, Position) 分组
    User = get_user_model()
    
    # 仅获取当前页面项目的统计信息
    role_stats_qs = User.objects.filter(
        project_memberships__in=current_page_projects
    ).values(
        'project_memberships', 'profile__position'
    ).annotate(
        count=models.Count('id')
    )
    
    # 在内存中处理统计信息
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
        
    # Permission Check for Create Button
    can_create_project = has_manage_permission(request.user)

    return render(request, 'reports/teams.html', {
        'can_create_project': can_create_project,
        'users': page_obj,
        'page_obj': page_obj,
        'member_per_page': member_per_page,
        'project_page_obj': project_page_obj,
        'project_per_page': project_per_page,
        'q': q,
        'role': role,
        'project_filter': project_filter,
        'roles': Profile.ROLE_CHOICES,
        'can_update_role': request.user.is_superuser,
        'total_count': page_obj.paginator.count,
        'projects': dropdown_projects, # 下拉菜单的轻量级查询
        'project_teams': project_teams, # 卡片的处理数据
        'today_date': timezone.now().strftime('%Y-%m-%d'),
    })


@login_required
@require_GET
def team_member_projects(request, user_id):
    target_user = get_object_or_404(get_user_model(), pk=user_id)
    manageable_projects = get_manageable_projects(request.user)
    if not request.user.is_superuser and not manageable_projects.exists():
        return _team_json_error('无可管理项目 / No manageable projects', 403)
    return JsonResponse({
        'status': 'success',
        **_member_project_payload(request.user, target_user),
    })


@login_required
@require_POST
def team_member_update_role(request, user_id):
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Permission denied'}, status=403)
        
    new_role = request.POST.get('role')
    success, message = team_service.update_member_role(user_id, new_role, changed_by=request.user)
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.accepts('application/json'):
        if success:
            # Broadcast
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "team_updates_global",
                {
                    "type": "team_update",
                    "user_id": user_id,
                    "action": "update_role",
                    "data": {
                        "role": new_role,
                        "role_display": dict(Profile.ROLE_CHOICES).get(new_role, new_role)
                    },
                    "sender_id": request.user.id
                }
            )
            return JsonResponse({'status': 'success', 'message': message})
        else:
            return JsonResponse({'status': 'error', 'message': message}, status=400)

    if success:
        messages.success(request, message)
        log_action(request, 'update', f"user_role {user_id} -> {new_role}")
    else:
        messages.error(request, message)
        
    return redirect('reports:teams')

@login_required
@require_POST
def team_member_add_project(request, user_id):
    project_id = request.POST.get('project_id')
    if not project_id or not str(project_id).isdigit():
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return _team_json_error('请选择项目 / Please select a project', 400)
        messages.error(request, "Please select a project")
        return redirect('reports:teams')

    try:
        project = get_manageable_projects(request.user).get(pk=project_id)
    except Project.DoesNotExist:
        return _team_json_error('项目不存在、已停用或无管理权限 / Project unavailable or permission denied', 403)

    success, message = team_service.add_member_to_project(user_id, project_id, changed_by=request.user)
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.accepts('application/json'):
        if success:
            target_user = get_object_or_404(get_user_model(), pk=user_id)
            payload = _member_project_payload(request.user, target_user)
            log_action(
                request,
                'update',
                f"user_project_add {user_id} -> {project_id}",
                data={'user_id': user_id, 'project_id': project.id, 'project_code': project.code},
            )
            
            # Broadcast
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "team_updates_global",
                {
                    "type": "team_update",
                    "user_id": user_id,
                    "action": "add_project",
                    "data": {'project_id': project.id},
                    "sender_id": request.user.id
                }
            )
            return JsonResponse({'status': 'success', 'message': message, **payload})
        else:
            return JsonResponse({'status': 'error', 'message': message}, status=400)

    if success:
        messages.success(request, message)
        log_action(request, 'update', f"user_project_add {user_id} -> {project_id}")
    else:
        messages.error(request, message)
        
    return redirect('reports:teams')

@login_required
@require_POST
def team_member_remove_project(request, user_id, project_id):
    try:
        project = get_manageable_projects(request.user).get(pk=project_id)
    except Project.DoesNotExist:
        return _team_json_error('项目不存在、已停用或无管理权限 / Project unavailable or permission denied', 403)
        
    success, message = team_service.remove_member_from_project(user_id, project_id, changed_by=request.user)
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.accepts('application/json'):
        if success:
            target_user = get_object_or_404(get_user_model(), pk=user_id)
            payload = _member_project_payload(request.user, target_user)
            log_action(
                request,
                'update',
                f"user_project_remove {user_id} -> {project_id}",
                data={'user_id': user_id, 'project_id': project.id, 'project_code': project.code},
            )
            
            # Broadcast
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "team_updates_global",
                {
                    "type": "team_update",
                    "user_id": user_id,
                    "action": "remove_project",
                    "data": {'project_id': project.id},
                    "sender_id": request.user.id
                }
            )
            return JsonResponse({'status': 'success', 'message': message, **payload})
        else:
            return JsonResponse({'status': 'error', 'message': message}, status=400)

    if success:
        messages.success(request, message)
        log_action(request, 'update', f"user_project_remove {user_id} -> {project_id}")
    else:
        messages.error(request, message)
        
    return redirect('reports:teams')
