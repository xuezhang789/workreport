from django import template
from reports.utils import can_manage_project as check_manage_project
from core.services.rbac import RBACService

register = template.Library()

@register.simple_tag(takes_context=True)
def can_manage_project(context, project):
    """
    Check if current user can manage the given project.
    Usage: {% can_manage_project project as can_manage %}
    """
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return False
    return check_manage_project(request.user, project)

@register.simple_tag(takes_context=True)
def has_perm(context, permission_code, scope=None):
    """
    Check if current user has specific RBAC permission.
    Usage: {% has_perm 'project.view' scope='project:1' as can_view %}
    """
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return False
        
    return RBACService.has_permission(request.user, permission_code, scope=scope)

@register.simple_tag(takes_context=True)
def has_permission(context, permission_code):
    """
    Alias for has_perm without scope (for backward compatibility or simpler usage).
    Usage: {% has_permission 'project.create' as can_create %}
    """
    return has_perm(context, permission_code, scope=None)
