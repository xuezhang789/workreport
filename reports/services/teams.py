from django.contrib.auth import get_user_model
from django.db.models import Q, Prefetch
from ..models import Profile, Project

def get_team_members(q=None, role=None, project_id=None, visible_projects=None):
    """
    获取过滤后的团队成员列表。
    """
    User = get_user_model()
    project_queryset = Project.objects.only(
        'id', 'name', 'code', 'overall_progress'
    ).order_by('name')
    if visible_projects is not None:
        project_queryset = project_queryset.filter(pk__in=visible_projects.values('pk'))

    project_prefetch = Prefetch(
        'project_memberships',
        queryset=project_queryset,
    )
    qs = User.objects.select_related('profile', 'preferences').prefetch_related(project_prefetch).order_by('username')
    
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
        
    return qs.distinct()

def update_member_role(user_id, new_role, changed_by=None):
    """
    更新用户角色。
    """
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
        if new_role not in dict(Profile.ROLE_CHOICES):
            return False, "Invalid role selected"

        # Legacy/imported users may not have a Profile row yet.
        Profile.objects.update_or_create(
            user=user,
            defaults={'position': new_role},
        )
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
            return False, "用户已在该项目中 / User already in project"
            
        project.members.add(user)
        return True, f"已将 {user.username} 添加至 {project.name} / Member added"
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

        if not project.members.filter(id=user_id).exists():
            return False, "用户不在该项目中 / User is not assigned to project"

        project.members.remove(user)
        return True, f"已将 {user.username} 移出 {project.name} / Member removed"
    except (User.DoesNotExist, Project.DoesNotExist):
        return False, "User or Project not found"
    except Exception as e:
        return False, str(e)
