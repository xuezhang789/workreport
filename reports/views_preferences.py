from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from core.models import UserPreference
from core.services.preferences import (
    MAX_PREFERENCE_SECTION_BYTES,
    normalize_ui_preferences,
    remember_ui_preferences,
)
import json


ALLOWED_PREFERENCE_KEYS = {'profile', 'privacy', 'notify', 'ui', 'dashboard'}


@login_required
def preference_get_api(request):
    key = (request.GET.get('key') or '').strip()
    if key and key not in ALLOWED_PREFERENCE_KEYS:
        return JsonResponse({'error': 'invalid key'}, status=400)
    try:
        pref = request.user.preferences
        data = pref.data or {}
    except UserPreference.DoesNotExist:
        data = {}

    if not key:
        return JsonResponse({'data': data})
    value = normalize_ui_preferences(data.get('ui')) if key == 'ui' else data.get(key, {})
    if key == 'ui':
        remember_ui_preferences(request.session, value)
    return JsonResponse({'data': value})


@login_required
def preference_save_api(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    key = (request.POST.get('key') or '').strip()
    if key not in ALLOWED_PREFERENCE_KEYS:
        return JsonResponse({'error': 'invalid key'}, status=400)
    try:
        value = json.loads(request.POST.get('value') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'invalid value'}, status=400)
    if not isinstance(value, dict):
        return JsonResponse({'error': 'invalid value'}, status=400)
    if len(json.dumps(value, ensure_ascii=False)) > MAX_PREFERENCE_SECTION_BYTES:
        return JsonResponse({'error': 'value too large'}, status=400)
    if key == 'ui':
        value = normalize_ui_preferences(value)

    pref, _ = UserPreference.objects.get_or_create(user=request.user, defaults={'data': {}})
    pref.update_section(key, value)
    if key == 'ui':
        remember_ui_preferences(request.session, value)
    return JsonResponse({'ok': True})
