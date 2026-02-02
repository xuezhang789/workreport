from django.contrib.auth import get_user_model
from django.db.models import Q
from ..models import Profile, Project

def get_team_members(q=None, role=None, project_id=None):
    """
    获取过滤后的团队成员列表。
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
        
    if role:
        qs = qs.filter(profile__position=role)
        
    if project_id:
        qs = qs.filter(project_memberships__id=project_id)
        
    return qs

def update_member_role(user_id, new_role, changed_by=None):
    """
    更新用户角色。
    """
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
        if new_role not in dict(Profile.ROLE_CHOICES):
            return False, "Invalid role selected"
            
        user.profile.position = new_role
        user.profile.save()
        return True, f"Role updated to {new_role} for {user.username}"
    except User.DoesNotExist:
        return False, "User not found"
    except Exception as e:
        return False, str(e)

def add_member_to_project(user_id, project_id, changed_by=None):
    """
    将用户添加到项目。
    """
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
        project = Project.objects.get(id=project_id)
        
        if project.members.filter(id=user_id).exists():
            return False, "User already in project"
            
        project.members.add(user)
        return True, f"Added {user.username} to {project.name}"
    except (User.DoesNotExist, Project.DoesNotExist):
        return False, "User or Project not found"
    except Exception as e:
        return False, str(e)

def remove_member_from_project(user_id, project_id, changed_by=None):
    """
    从项目中移除用户。
    """
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
        project = Project.objects.get(id=project_id)
        
        project.members.remove(user)
        return True, f"Removed {user.username} from {project.name}"
    except (User.DoesNotExist, Project.DoesNotExist):
        return False, "User or Project not found"
    except Exception as e:
        return False, str(e)
