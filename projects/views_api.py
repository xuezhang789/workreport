from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.contrib.auth import get_user_model
from django.db import transaction

from projects.models import Project
from reports.utils import can_manage_project
from audit.utils import log_action

@login_required
@require_POST
def project_manage_members_api(request, project_id):
    """
    API to manage project members, managers, and owner.
    Action: add_member, remove_member, add_manager, remove_manager, set_owner
    """
    project = get_object_or_404(Project, pk=project_id)
    
    # Permission Check: Must be Superuser or Project Owner
    # Note: Even regular Managers might not be allowed to change Owner or other Managers depending on policy.
    # For now, let's restrict to Superuser and Owner for sensitive changes (Owner, Managers),
    # and allow Managers to change Members.
    
    is_superuser = request.user.is_superuser
    is_owner = (request.user == project.owner)
    is_manager = project.managers.filter(pk=request.user.pk).exists()
    
    if not (is_superuser or is_owner or is_manager):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    action = request.POST.get('action')
    user_id = request.POST.get('user_id')
    
    if not action or not user_id:
        return JsonResponse({'error': 'Missing parameters'}, status=400)
        
    try:
        target_user = get_user_model().objects.get(pk=user_id)
    except get_user_model().DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)

    try:
        with transaction.atomic():
            if action == 'set_owner':
                if not (is_superuser or is_owner): # Only Owner/Superuser can transfer ownership
                    return JsonResponse({'error': 'Permission denied'}, status=403)
                
                old_owner = project.owner
                project.owner = target_user
                project.save(update_fields=['owner'])
                
                # Ensure new owner is in members? Not strictly required by model but good practice?
                # Usually owner doesn't need to be in members list to have access.
                
                log_action(request, 'update', f"project {project.id} set_owner {old_owner} -> {target_user}")
                return JsonResponse({'status': 'success', 'message': f'Owner changed to {target_user.get_full_name() or target_user.username}'})

            elif action == 'add_manager':
                if not (is_superuser or is_owner):
                    return JsonResponse({'error': 'Permission denied'}, status=403)
                    
                project.managers.add(target_user)
                log_action(request, 'update', f"project {project.id} add_manager {target_user}")
                return JsonResponse({'status': 'success'})

            elif action == 'remove_manager':
                if not (is_superuser or is_owner):
                    return JsonResponse({'error': 'Permission denied'}, status=403)
                
                project.managers.remove(target_user)
                log_action(request, 'update', f"project {project.id} remove_manager {target_user}")
                return JsonResponse({'status': 'success'})

            elif action == 'add_member':
                # Managers can add members
                if project.members.filter(pk=target_user.pk).exists():
                     return JsonResponse({'status': 'success', 'message': 'Already a member'})
                     
                project.members.add(target_user)
                log_action(request, 'update', f"project {project.id} add_member {target_user}")
                return JsonResponse({'status': 'success'})

            elif action == 'remove_member':
                # Managers can remove members
                project.members.remove(target_user)
                log_action(request, 'update', f"project {project.id} remove_member {target_user}")
                return JsonResponse({'status': 'success'})

            else:
                return JsonResponse({'error': 'Invalid action'}, status=400)
                
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def project_users_api(request, project_id):
    """
    Get detailed list of users in a project for the modal.
    """
    project = get_object_or_404(Project, pk=project_id)
    
    if not can_manage_project(request.user, project):
         return JsonResponse({'error': 'Permission denied'}, status=403)
         
    def _format_user(u):
        if not u: return None
        return {
            'id': u.id,
            'username': u.username,
            'full_name': u.get_full_name() or u.username,
            'email': u.email,
            'avatar_char': (u.get_full_name() or u.username)[0].upper()
        }

    return JsonResponse({
        'owner': _format_user(project.owner),
        'managers': [_format_user(u) for u in project.managers.all()],
        'members': [_format_user(u) for u in project.members.all()]
    })

@login_required
def get_user_responsible_projects(request, user_id):
    """
    Get list of projects where user is owner or manager.
    Path: /api/v1/users/{userId}/responsible-projects
    """
    # Permission Check: Self or Superuser
    if request.user.id != user_id and not request.user.is_superuser:
        return JsonResponse({'error': 'Permission denied'}, status=403)
        
    try:
        user = get_user_model().objects.get(pk=user_id)
    except get_user_model().DoesNotExist:
        return JsonResponse({'error': 'User not found'}, status=404)
        
    from django.db.models import Q
    
    # Query projects where user is owner or manager
    # Also check if project is active? Usually yes for task creation.
    projects = Project.objects.filter(
        (Q(owner=user) | Q(managers=user)) & Q(is_active=True)
    ).distinct().order_by('name')
    
    data = []
    for p in projects:
        data.append({
            'projectId': p.id,
            'projectName': p.name,
            'projectCode': p.code,
            'ownerName': p.owner.get_full_name() or p.owner.username if p.owner else '未分配',
            'phase': p.current_phase.phase_name if p.current_phase else '',
            'progress': float(p.overall_progress),
            'isActive': p.is_active,
        })
        
    return JsonResponse(data, safe=False)
