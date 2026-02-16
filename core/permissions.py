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


