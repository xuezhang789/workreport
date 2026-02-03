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
    if None in scopes:
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
    # Base RBAC access
    rbac_projects = _get_projects_by_permission(user, 'project.view')
    
    if user.is_superuser:
        return rbac_projects
        
    # Combine with M2M membership (Members implicitly have view access)
    return (rbac_projects | Project.objects.filter(members=user, is_active=True)).distinct()

def can_manage_project(user, project):
    """
    Check if user has edit/manage permission for a specific project.
    检查用户是否拥有特定项目的编辑/管理权限。
    """
    scope = f"project:{project.id}"
    return RBACService.has_permission(user, 'project.manage', scope=scope)

def get_manageable_projects(user):
    """
    Returns QuerySet of projects the user can manage (edit/update).
    返回用户可以管理（编辑/更新）的项目查询集。
    """
    return _get_projects_by_permission(user, 'project.manage')

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
