from django.core.cache import cache
from django.db.models import Q
from projects.models import Project
from tasks.models import Task
from work_logs.models import DailyReport
from core.services.rbac import RBACService

def _get_projects_by_permission(user, permission_code):
    """Helper to get projects where user has specific permission"""
    """获取用户拥有特定权限的项目的辅助函数"""
    if not user.is_authenticated:
        return Project.objects.none()
    
    if user.is_superuser:
        return Project.objects.filter(is_active=True)
        
    scopes = RBACService.get_scopes_with_permission(user, permission_code)
    
    # If None (Global) is in scopes, return all active projects
    # 如果 scopes 中包含 None（全局），则返回所有活动项目
    if None in scopes or '' in scopes:
        return Project.objects.filter(is_active=True)
        
    # Extract project IDs from scopes like 'project:123'
    # 从类似 'project:123' 的 scope 中提取项目 ID
    project_ids = []
    for s in scopes:
        if s and s.startswith('project:'):
            try:
                pid = int(s.split(':')[1])
                project_ids.append(pid)
            except (ValueError, IndexError):
                continue
                
    return Project.objects.filter(id__in=project_ids, is_active=True)

def get_accessible_projects(user):
    """
    Returns a QuerySet of projects accessible to the user (view permission).
    返回用户可访问（查看权限）的项目查询集。
    """
    if not user.is_authenticated:
        return Project.objects.none()

    if user.is_superuser:
        return Project.objects.filter(is_active=True)

    cache_key = f"accessible_projects_ids:{user.id}"
    cached_ids = cache.get(cache_key)

    if cached_ids is not None:
        return Project.objects.filter(id__in=cached_ids, is_active=True)

    # Base RBAC access
    rbac_projects = _get_projects_by_permission(user, 'project.view')
    
    # Combine with Model fields (Owner, Managers, Members)
    # 结合模型字段（负责人，管理员，成员）
    # Note: RBAC is powerful but we must respect the direct database relationships too.
    direct_access = Project.objects.filter(
        Q(members=user) | Q(managers=user) | Q(owner=user),
        is_active=True
    )
    
    # Combine and distinct
    final_qs = (rbac_projects | direct_access).distinct()
    
    # Cache the IDs
    ids = list(final_qs.values_list('id', flat=True))
    cache.set(cache_key, ids, 300) # Cache for 5 minutes
    
    return Project.objects.filter(id__in=ids)

def can_manage_project(user, project):
    """
    Check if user has edit/manage permission for a specific project.
    检查用户是否拥有特定项目的编辑/管理权限。
    """
    if not user.is_authenticated:
        return False
        
    if user.is_superuser:
        return True
        
    # Cache key for this specific check
    cache_key = f"can_manage_project:{user.id}:{project.id}"
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return cached_result

    result = False
    # Check Project model fields directly (Owner/Managers)
    # 检查 Project 模型字段（负责人/管理员）
    if user == project.owner:
        result = True
    elif project.managers.filter(pk=user.pk).exists():
        result = True
    else:
        # Check RBAC permissions (if assigned via Role)
        scope = f"project:{project.id}"
        if RBACService.has_permission(user, 'project.manage', scope=scope):
            result = True
    
    cache.set(cache_key, result, 300)
    return result

def get_manageable_projects(user):
    """
    Returns QuerySet of projects the user can manage (edit/update).
    返回用户可以管理（编辑/更新）的项目查询集。
    """
    if user.is_superuser:
        return Project.objects.filter(is_active=True)

    rbac_projects = _get_projects_by_permission(user, 'project.manage')
    
    # Combine with direct Model ownership/management
    direct_manage = Project.objects.filter(
        Q(managers=user) | Q(owner=user),
        is_active=True
    )
    
    return (rbac_projects | direct_manage).distinct()

def get_accessible_tasks(user):
    """
    Returns a QuerySet of tasks in accessible projects.
    返回可访问项目中的任务查询集。
    """
    if not user.is_authenticated:
        return Task.objects.none()
    
    if user.is_superuser:
        return Task.objects.all()

    projects = get_accessible_projects(user)
    return Task.objects.filter(project__in=projects).distinct()

def get_accessible_reports(user):
    """
    Returns daily reports visible to the user.
    返回用户可见的日报。
    """
    if not user.is_authenticated:
        return DailyReport.objects.none()
    
    if user.is_superuser:
        return DailyReport.objects.all()

    projects = get_accessible_projects(user)
    
    # Reports that are linked to any of the accessible projects
    # 链接到任何可访问项目的日报
    return DailyReport.objects.filter(projects__in=projects).distinct()

def clear_project_permission_cache(user, project=None):
    """
    Clear permission caches for a user.
    If project is provided, clears specific project permission cache.
    Always clears the list of accessible projects.
    """
    if not user:
        return
        
    # Clear accessible projects list cache
    cache.delete(f"accessible_projects_ids:{user.id}")
    
    # Clear specific project permission cache
    if project:
        cache.delete(f"can_manage_project:{user.id}:{project.id}")
    else:
        # If no project specified, we can't easily clear all specific project keys 
        # unless we use a pattern match which django cache doesn't always support efficiently.
        # Ideally, we should iterate if we knew which projects.
        # For now, we rely on the short TTL (5 mins) or specific calls.
        pass
