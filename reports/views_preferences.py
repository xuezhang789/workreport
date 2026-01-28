from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from core.models import UserPreference


@login_required
def preference_get_api(request):
    pref, _ = UserPreference.objects.get_or_create(user=request.user, defaults={'data': {}})
    key = (request.GET.get('key') or '').strip()
    if not key:
        return JsonResponse({'data': pref.data})
    return JsonResponse({'data': pref.data.get(key, {})})


@login_required
def preference_save_api(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)
    key = (request.POST.get('key') or '').strip()
    try:
        import json
        value = json.loads(request.POST.get('value') or '{}')
    except Exception:
        return JsonResponse({'error': 'invalid value'}, status=400)
    pref, _ = UserPreference.objects.get_or_create(user=request.user, defaults={'data': {}})
    data = pref.data or {}
    data[key] = value
    pref.data = data
    pref.save(update_fields=['data', 'updated_at'])
    return JsonResponse({'ok': True})
