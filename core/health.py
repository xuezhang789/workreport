import hmac
import uuid

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@never_cache
@require_GET
def liveness(request):
    return JsonResponse({'status': 'ok'})


@never_cache
@require_GET
def readiness(request):
    checks = {'database': _check_database, 'cache': _check_cache}
    results = {}
    ready = True
    for name, check in checks.items():
        try:
            check()
            results[name] = 'ok'
        except Exception as exc:
            ready = False
            results[name] = 'error'
            if settings.DEBUG:
                results[f'{name}_detail'] = str(exc)
    return JsonResponse(
        {'status': 'ready' if ready else 'not_ready', 'checks': results},
        status=200 if ready else 503,
    )


@never_cache
@require_GET
def metrics(request):
    token = getattr(settings, 'METRICS_TOKEN', '')
    supplied = request.headers.get('Authorization', '').removeprefix('Bearer ').strip()
    if not settings.DEBUG and (not token or not hmac.compare_digest(supplied, token)):
        raise Http404
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    except ImportError as exc:
        return HttpResponse(str(exc), status=503, content_type='text/plain')
    return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)


def _check_database():
    with connections['default'].cursor() as cursor:
        cursor.execute('SELECT 1')
        cursor.fetchone()


def _check_cache():
    key = f'health:{uuid.uuid4().hex}'
    cache.set(key, 'ok', timeout=5)
    if cache.get(key) != 'ok':
        raise RuntimeError('cache round-trip failed')
    cache.delete(key)
