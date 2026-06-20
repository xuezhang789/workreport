import logging
import re
import time
import uuid
from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

from core.observability import request_id_context


logger = logging.getLogger('workreport.request')
REQUEST_ID_PATTERN = re.compile(r'^[A-Za-z0-9._:-]{1,128}$')

try:
    from prometheus_client import Counter, Histogram

    REQUEST_COUNT = Counter(
        'workreport_http_requests_total',
        'HTTP requests handled by WorkReport.',
        ('method', 'view', 'status'),
    )
    REQUEST_DURATION = Histogram(
        'workreport_http_request_duration_seconds',
        'WorkReport HTTP request duration.',
        ('method', 'view'),
    )
except ImportError:
    REQUEST_COUNT = None
    REQUEST_DURATION = None


class RequestObservabilityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied_request_id = request.headers.get('X-Request-ID', '')
        request_id = supplied_request_id if REQUEST_ID_PATTERN.fullmatch(supplied_request_id) else uuid.uuid4().hex
        request.request_id = request_id
        token = request_id_context.set(request_id)
        started = time.monotonic()
        try:
            response = self.get_response(request)
        except Exception:
            logger.exception(
                'request_failed',
                extra={
                    'method': request.method,
                    'path': request.path,
                    'duration_ms': round((time.monotonic() - started) * 1000, 2),
                },
            )
            request_id_context.reset(token)
            raise

        duration = time.monotonic() - started
        response['X-Request-ID'] = request_id
        view_name = self._view_name(request)
        user = getattr(request, 'user', None)
        logger.info(
            'request_completed',
            extra={
                'method': request.method,
                'path': request.path,
                'view': view_name,
                'status': response.status_code,
                'duration_ms': round(duration * 1000, 2),
                'user_id': user.pk if getattr(user, 'is_authenticated', False) else None,
            },
        )
        if REQUEST_COUNT is not None:
            REQUEST_COUNT.labels(request.method, view_name, str(response.status_code)).inc()
            REQUEST_DURATION.labels(request.method, view_name).observe(duration)
        request_id_context.reset(token)
        return response

    @staticmethod
    def _view_name(request):
        match = getattr(request, 'resolver_match', None)
        return match.view_name if match and match.view_name else 'unresolved'


class SuperuserMFAMiddleware:
    EXEMPT_PREFIXES = (
        '/healthz', '/readyz', '/metrics', '/static/',
        '/core/login/', '/accounts/login/', '/core/logout/', '/accounts/logout/',
        '/core/mfa/', '/accounts/mfa/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if (
            settings.MFA_REQUIRED_FOR_SUPERUSERS
            and getattr(user, 'is_authenticated', False)
            and user.is_superuser
            and not request.path.startswith(self.EXEMPT_PREFIXES)
        ):
            next_path = request.get_full_path()
            if not user.is_verified():
                from django_otp import devices_for_user
                route = 'core:mfa_verify' if any(devices_for_user(user, confirmed=True)) else 'core:mfa_setup'
                return redirect(f"{reverse(route)}?{urlencode({'next': next_path})}")
        return self.get_response(request)
