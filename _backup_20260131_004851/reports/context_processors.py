from django.contrib.auth import get_user_model


def admin_flags(request):
    """Provide admin-related flags for templates."""

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
    if is_authenticated and hasattr(user, "managed_projects"):
        has_managed_projects = user.managed_projects.exists()
    else:
        has_managed_projects = False

    can_view_admin_global = is_staff
    can_view_admin_project = is_staff or has_manage_role or has_managed_projects

    return {
        "can_view_admin_global": can_view_admin_global,
        "can_view_admin_project": can_view_admin_project,
    }
