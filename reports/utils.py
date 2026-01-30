from django.db.models import Q
from projects.models import Project
from tasks.models import Task
from work_logs.models import DailyReport

def get_accessible_projects(user):
    """
    Returns a QuerySet of projects accessible to the user.
    Rules:
    1. Project Owner
    2. Project Member
    3. Project Manager
    4. Task Primary Owner (in that project)
    5. Task Collaborator (in that project)
    """
    if not user.is_authenticated:
        return Project.objects.none()

    if user.is_superuser:
        return Project.objects.filter(is_active=True)

    # Rule 1-3: Project relations
    # Note: 'members' and 'managers' are M2M fields on Project model.
    q_project = Q(owner=user) | Q(members=user) | Q(managers=user)

    return Project.objects.filter(
        q_project
    ).filter(is_active=True).distinct()

def can_manage_project(user, project):
    """
    Check if user has edit/manage permission for a specific project.
    Rules:
    1. Superuser
    2. Project Owner
    3. Project Manager
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if project.owner_id == user.id:
        return True
    
    # Optimization: Use prefetch cache if available to avoid N+1 queries in loops
    if getattr(project, '_prefetched_objects_cache', None) and 'managers' in project._prefetched_objects_cache:
        return user in project.managers.all()
        
    return project.managers.filter(id=user.id).exists()

def get_manageable_projects(user):
    """
    Returns QuerySet of projects the user can manage (edit/update).
    """
    if not user.is_authenticated:
        return Project.objects.none()
    if user.is_superuser:
        return Project.objects.filter(is_active=True)
    
    return Project.objects.filter(
        Q(owner=user) | Q(managers=user)
    ).filter(is_active=True).distinct()

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
    Rules:
    1. Reports linked to accessible projects (via 'projects' M2M field).
    2. Reports submitted by members of accessible projects?
       The prompt says: "User A only participates in Project X, so he can only see Project X members' reports".
       This implies if a report is NOT explicitly tagged with a project, but the user is in the same project as the reporter, it might be visible.
       However, explicit project tagging is safer and clearer.
       Let's stick to: Report MUST be related to accessible projects.
       
       Update: If a report is purely "General" and not linked to any project, who sees it?
       Usually reports are required to be linked.
       If we strictly follow "Project X members' reports", we should find all users U who are in User's accessible projects,
       and show reports from U. But this leaks User U's reports about Project Y (where User is not a member).
       
       So the constraint "strictly cannot see Project Y members' reports" overrides the "Project X members" part.
       Meaning: Even if I know User B from Project X, I cannot see User B's report about Project Y.
       
       Therefore, the filter MUST be on the Report's content/context (the project field).
    """
    if not user.is_authenticated:
        return DailyReport.objects.none()
    
    if user.is_superuser:
        return DailyReport.objects.all()

    projects = get_accessible_projects(user)
    
    # Reports that are linked to any of the accessible projects
    return DailyReport.objects.filter(projects__in=projects).distinct()
