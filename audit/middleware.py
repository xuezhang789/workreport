import threading
from asgiref.local import Local

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
        
        response = self.get_response(request)
        
        # Cleanup (Local handles this better but explicit cleanup is good practice)
        if hasattr(_thread_locals, 'user'): del _thread_locals.user
        if hasattr(_thread_locals, 'request'): del _thread_locals.request
        if hasattr(_thread_locals, 'ip'): del _thread_locals.ip
            
        return response

    def _get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
