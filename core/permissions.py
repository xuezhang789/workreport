from core.services.rbac import RBACService

def has_manage_permission(user):
    """
    Check if user has global management permission (Staff or Manager role).
    检查用户是否具有全局管理权限（Staff 或 Manager 角色）。
    """
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    
    # Check for global 'project.manage' permission
    # 检查全局 'project.manage' 权限
    return RBACService.has_permission(user, 'project.manage', scope=None)

def has_project_manage_permission(user, project):
    """
    Check if user can manage a specific project.
    检查用户是否可以管理指定项目。
    """
    scope = f"project:{project.id}"
    return RBACService.has_permission(user, 'project.manage', scope=scope)

class ProjectAccessMixin:
    """
    Mixin for Class Based Views to enforce project access.
    用于基于类的视图（CBV）以强制执行项目访问控制的 Mixin。
    """
    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_superuser:
            return qs
        
        from reports.utils import get_accessible_projects
        accessible = get_accessible_projects(self.request.user)
        return qs.filter(project__in=accessible)
