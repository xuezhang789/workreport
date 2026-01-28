from core.models import Profile

MANAGER_ROLES = {'mgr', 'pm'}

def has_manage_permission(user):
    """
    Check if user has global management permission (Staff or Manager role).
    """
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    try:
        return user.profile.position in MANAGER_ROLES
    except Profile.DoesNotExist:
        return False

def has_project_manage_permission(user, project):
    """
    Check if user can manage a specific project.
    """
    if has_manage_permission(user):
        return True
    if project.owner_id == user.id:
        return True
    # Optimization: Use prefetch cache if available to avoid N+1 queries
    if hasattr(project, '_prefetched_objects_cache') and 'managers' in project._prefetched_objects_cache:
        return any(m.id == user.id for m in project.managers.all())
    return project.managers.filter(id=user.id).exists()

class ProjectAccessMixin:
    """
    Mixin for Class Based Views to enforce project access.
    """
    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_superuser:
            return qs
        # Need to import here to avoid circular dependency if possible, 
        # or rely on logic that doesn't import reports.utils
        # For now, let's keep it abstract or use helper
        from reports.utils import get_accessible_projects
        accessible = get_accessible_projects(self.request.user)
        return qs.filter(project__in=accessible)
