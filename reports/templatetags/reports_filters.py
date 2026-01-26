from django import template
from django.core.exceptions import ObjectDoesNotExist

register = template.Library()

@register.filter
def get_avatar_url(user):
    """
    Safely get user avatar URL from UserPreference.
    """
    try:
        if user.is_authenticated:
            return user.preferences.data.get('profile', {}).get('avatar_data_url')
    except (ObjectDoesNotExist, AttributeError):
        pass
    return None

@register.filter
def mask_email(email):
    """
    Mask email address for privacy.
    Example: arlo@example.com -> a***o@example.com
    """
    if not email or '@' not in email:
        return email
    
    try:
        local, domain = email.split('@', 1)
        if len(local) <= 2:
            masked_local = local[0] + "***"
        else:
            masked_local = local[0] + "***" + local[-1]
        return f"{masked_local}@{domain}"
    except Exception:
        return email
