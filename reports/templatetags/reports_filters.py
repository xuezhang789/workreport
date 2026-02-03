from django import template
from django.core.exceptions import ObjectDoesNotExist
import json
from django.utils.safestring import mark_safe

register = template.Library()

@register.filter
def get_avatar_url(user):
    """
    从 UserPreference 安全地获取用户头像 URL。
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
    为了隐私屏蔽电子邮件地址。
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

@register.filter
def pretty_json(value):
    """
    将字典格式化为漂亮的 JSON 字符串。
    """
    try:
        if isinstance(value, str):
            value = json.loads(value)
        return mark_safe(json.dumps(value, indent=2, ensure_ascii=False))
    except Exception:
        return value

@register.filter
def to_project_json(projects):
    """
    将项目 QuerySet 序列化为 JSON 字符串 (id, name, code)
    """
    try:
        data = [{'id': p.id, 'name': p.name, 'code': p.code} for p in projects]
        return mark_safe(json.dumps(data, ensure_ascii=False))
    except Exception:
        return "[]"
