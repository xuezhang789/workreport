from asgiref.local import Local
from django.conf import settings

_thread_locals = Local()

def get_current_user():
    return getattr(_thread_locals, 'user', None)

def get_current_request():
    return getattr(_thread_locals, 'request', None)

def get_current_ip():
    return getattr(_thread_locals, 'ip', None)

class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_locals.user = getattr(request, 'user', None)
        _thread_locals.request = request
        _thread_locals.ip = self._get_client_ip(request)

        try:
            return self.get_response(request)
        finally:
            for attribute in ('user', 'request', 'ip'):
                if hasattr(_thread_locals, attribute):
                    delattr(_thread_locals, attribute)

    def _get_client_ip(self, request):
        if getattr(settings, 'TRUST_PROXY_HEADERS', False):
            real_ip = request.META.get('HTTP_X_REAL_IP')
            if real_ip:
                return real_ip.strip()
        return request.META.get('REMOTE_ADDR')
