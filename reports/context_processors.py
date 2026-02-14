from django.contrib.auth import get_user_model


def admin_flags(request):
    """Provide admin-related flags for templates."""
    """为模板提供管理相关的标志。"""

    user = request.user
    is_authenticated = getattr(user, "is_authenticated", False)
    is_staff = bool(is_authenticated and getattr(user, "is_staff", False))

    role = ""
    try:
        role = user.profile.position
    except Exception:
        role = ""

    has_manage_role = role in ("mgr", "pm")

    # 避免 AnonymousUser 触发多余查询
    # 优化：如果已经是员工或管理角色，则无需检查 managed_projects（因为 can_view_admin_project 将为 True）
    # Optimization: If already staff or manage role, no need to check managed_projects (can_view_admin_project will be True)
    if is_authenticated and hasattr(user, "managed_projects"):
        if is_staff or has_manage_role:
             # Skip query if already permitted
             has_managed_projects = False # Not strictly needed for logic below
        else:
             has_managed_projects = user.managed_projects.exists()
    else:
        has_managed_projects = False

    can_view_admin_global = is_staff
    can_view_admin_project = is_staff or has_manage_role or has_managed_projects

    return {
        "can_view_admin_global": can_view_admin_global,
        "can_view_admin_project": can_view_admin_project,
    }
