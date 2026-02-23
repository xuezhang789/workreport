from functools import wraps
from django.core.exceptions import PermissionDenied
from core.services.rbac import RBACService

def permission_required(permission_code, get_scope=None):
    """
    基于 RBAC 的权限检查装饰器。
    
    Args:
        permission_code (str): 权限代码 (e.g. 'project.view')
        get_scope (func): 从 request 获取 scope 字符串的函数。
                          函数签名: get_scope(request, *args, **kwargs) -> str or None
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            scope = get_scope(request, *args, **kwargs) if get_scope else None
            
            # 如果是超级用户，直接放行
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
                
            if not RBACService.has_permission(request.user, permission_code, scope):
                raise PermissionDenied(f"需要权限: {permission_code} (Scope: {scope})")
                
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
