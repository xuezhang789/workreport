from django.db.models import Q
from projects.models import Project
from tasks.models import Task
from work_logs.models import DailyReport
from core.services.rbac import RBACService

def _get_projects_by_permission(user, permission_code):
    """Helper to get projects where user has specific permission"""
    if not user.is_authenticated:
        return Project.objects.none()
    
    if user.is_superuser:
        return Project.objects.filter(is_active=True)
        
    scopes = RBACService.get_scopes_with_permission(user, permission_code)
    
    # If None (Global) is in scopes, return all active projects
    if None in scopes:
        return Project.objects.filter(is_active=True)
        
    # Extract project IDs from scopes like 'project:123'
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
    """
    return _get_projects_by_permission(user, 'project.view')

def can_manage_project(user, project):
    """
    Check if user has edit/manage permission for a specific project.
    """
    scope = f"project:{project.id}"
    return RBACService.has_permission(user, 'project.manage', scope=scope)

def get_manageable_projects(user):
    """
    Returns QuerySet of projects the user can manage (edit/update).
    """
    return _get_projects_by_permission(user, 'project.manage')

def get_accessible_tasks(user):
    """
    Returns a QuerySet of tasks in accessible projects.
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
    """
    if not user.is_authenticated:
        return DailyReport.objects.none()
    
    if user.is_superuser:
        return DailyReport.objects.all()

    projects = get_accessible_projects(user)
    
    # Reports that are linked to any of the accessible projects
    return DailyReport.objects.filter(projects__in=projects).distinct()
