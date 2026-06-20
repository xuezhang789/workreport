import time

# Compatibility imports for older modules; audit.middleware owns request context.
from audit.middleware import AuditMiddleware, get_current_ip, get_current_user

class TimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.time()
        response = self.get_response(request)
        duration = time.time() - start_time
        # 将持续时间添加到响应头
        response['X-Page-Generation-Duration-ms'] = int(duration * 1000)
        return response
