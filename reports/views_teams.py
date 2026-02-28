from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.db import models
from reports.models import Profile, Project
from reports.services import teams as team_service
from core.utils import _admin_forbidden
from core.permissions import has_manage_permission
from audit.utils import log_action
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model

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
        
        from reports.utils import get_manageable_projects
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
    
    # 过滤 'qs'（成员目录）
    # 理想情况下，我们是否应该只显示用户可以管理的项目的成员？
    # 或者成员目录是全局的？
    # 需求说“项目所有者……不能查看或操作其他项目”。
    # 这意味着他们不应该以暴露敏感信息的方式看到其他项目的成员？
    # 但目录通常允许查找人员以添加。
    # 让我们暂时保持成员目录原样（可搜索），或者如果严格要求则过滤它。
    # 需求：“项目所有者……不能访问其他项目”。
    # 这强烈建议过滤。
    
    if request.user.is_superuser:
        qs = team_service.get_team_members(q=q, role=role, project_id=project_filter)
    else:
        # 将成员搜索限制在可管理项目 + 也许是可访问项目？
        # 通常你想从整个公司池中添加新成员。
        # 所以 'get_team_members' (目录) 可能需要是所有用户，以便你可以找到他们来添加。
        # 但 'project_teams' (卡片) 必须被过滤。
        # 让我们保持目录开放（或者如果我们想严格控制可见性，则通过 `get_accessible_projects` 过滤）。
        # 但对于“团队管理”，通常你需要看看谁可用。
        # 让我们坚持：目录 = 所有用户（这样你可以添加他们）。
        qs = team_service.get_team_members(q=q, role=role, project_id=project_filter)
    
    # --- 成员目录分页 ---
    try:
        member_per_page = int(request.GET.get('member_per_page', 20))
        if member_per_page not in [10, 20, 50, 100]:
            member_per_page = 20
    except (ValueError, TypeError):
        member_per_page = 20

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
    try:
        project_per_page = int(request.GET.get('project_per_page', 20))
        if project_per_page not in [10, 20, 50, 100]:
            project_per_page = 20
    except (ValueError, TypeError):
        project_per_page = 20

    project_paginator = Paginator(dashboard_projects_qs, project_per_page)
    project_page_obj = project_paginator.get_page(request.GET.get('project_page'))
    current_page_projects = project_page_obj.object_list
    
    # 优化：批量获取角色统计信息，而不是每个项目循环
    # 按 (Project, Position) 分组
    from django.contrib.auth import get_user_model
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

    return render(request, 'reports/teams.html', {
        'users': page_obj,
        'page_obj': page_obj,
        'member_per_page': member_per_page,
        'project_page_obj': project_page_obj,
        'project_per_page': project_per_page,
        'q': q,
        'role': role,
        'project_filter': project_filter,
        'roles': Profile.ROLE_CHOICES,
        'total_count': qs.count(),
        'projects': dropdown_projects, # 下拉菜单的轻量级查询
        'project_teams': project_teams, # 卡片的处理数据
        'today_date': timezone.now().strftime('%Y-%m-%d'),
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
    if not project_id:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': "Please select a project"}, status=400)
        messages.error(request, "Please select a project")
        return redirect('reports:teams')

    # Security Check: Verify if user can manage THIS specific project
    from reports.utils import can_manage_project
    project = get_object_or_404(Project, pk=project_id)
    
    if not can_manage_project(request.user, project):
        return JsonResponse({'error': 'Permission denied for this project'}, status=403)

    success, message = team_service.add_member_to_project(user_id, project_id, changed_by=request.user)
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.accepts('application/json'):
        if success:
            # Get updated project list
            User = get_user_model()
            target_user = get_object_or_404(User, pk=user_id)
            projects = [{
                'id': p.id, 'name': p.name, 'code': p.code,
                'overall_progress': float(p.overall_progress)
            } for p in target_user.project_memberships.all()]
            
            # Broadcast
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "team_updates_global",
                {
                    "type": "team_update",
                    "user_id": user_id,
                    "action": "add_project",
                    "data": {'projects': projects},
                    "sender_id": request.user.id
                }
            )
            return JsonResponse({'status': 'success', 'message': message, 'projects': projects})
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
    # Security Check: Verify if user can manage THIS specific project
    from reports.utils import can_manage_project
    project = get_object_or_404(Project, pk=project_id)
    
    if not can_manage_project(request.user, project):
        return JsonResponse({'error': 'Permission denied for this project'}, status=403)
        
    success, message = team_service.remove_member_from_project(user_id, project_id, changed_by=request.user)
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.accepts('application/json'):
        if success:
            # Get updated project list
            User = get_user_model()
            target_user = get_object_or_404(User, pk=user_id)
            projects = [{
                'id': p.id, 'name': p.name, 'code': p.code,
                'overall_progress': float(p.overall_progress)
            } for p in target_user.project_memberships.all()]
            
            # Broadcast
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                "team_updates_global",
                {
                    "type": "team_update",
                    "user_id": user_id,
                    "action": "remove_project",
                    "data": {'projects': projects},
                    "sender_id": request.user.id
                }
            )
            return JsonResponse({'status': 'success', 'message': message, 'projects': projects})
        else:
            return JsonResponse({'status': 'error', 'message': message}, status=400)

    if success:
        messages.success(request, message)
        log_action(request, 'update', f"user_project_remove {user_id} -> {project_id}")
    else:
        messages.error(request, message)
        
    return redirect('reports:teams')
