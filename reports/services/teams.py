from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from reports.models import Profile, Project, DailyReport
import logging

logger = logging.getLogger(__name__)

def get_team_members(q=None, role=None, page=1, per_page=20):
    """
    Get paginated team members with filtering.
    """
    User = get_user_model()
    qs = User.objects.select_related('profile').prefetch_related('project_memberships').order_by('username')

    if q:
        qs = qs.filter(
            Q(username__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q) |
            Q(email__icontains=q)
        )
    
    if role and role in dict(Profile.ROLE_CHOICES):
        qs = qs.filter(profile__position=role)
        
    return qs

def update_member_role(user_id, new_role, changed_by=None):
    """
    Update a member's role.
    """
    if new_role not in dict(Profile.ROLE_CHOICES):
        raise ValueError("Invalid role")
        
    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
        profile, created = Profile.objects.get_or_create(user=user)
        old_role = profile.position
        
        if old_role != new_role:
            profile.position = new_role
            profile.save()
            logger.info(f"Role updated for user {user.username}: {old_role} -> {new_role} by {changed_by}")
            return True, f"Role updated to {new_role}"
            
        return False, "Role unchanged"
    except User.DoesNotExist:
        return False, "User not found"
    except Exception as e:
        logger.error(f"Error updating role: {e}")
        return False, str(e)

def add_member_to_project(user_id, project_id, changed_by=None):
    """
    Add a member to a project.
    """
    try:
        project = Project.objects.get(pk=project_id)
        User = get_user_model()
        user = User.objects.get(pk=user_id)
        
        if not project.members.filter(pk=user_id).exists():
            project.members.add(user)
            logger.info(f"User {user.username} added to project {project.code} by {changed_by}")
            return True, f"Added to {project.name}"
        return False, "Already a member"
    except (Project.DoesNotExist, User.DoesNotExist):
        return False, "Project or User not found"

def remove_member_from_project(user_id, project_id, changed_by=None):
    """
    Remove a member from a project.
    """
    try:
        project = Project.objects.get(pk=project_id)
        User = get_user_model()
        user = User.objects.get(pk=user_id)
        
        if project.members.filter(pk=user_id).exists():
            project.members.remove(user)
            logger.info(f"User {user.username} removed from project {project.code} by {changed_by}")
            return True, f"Removed from {project.name}"
        return False, "Not a member"
    except (Project.DoesNotExist, User.DoesNotExist):
        return False, "Project or User not found"
