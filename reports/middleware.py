import time


class TimingMiddleware:
    """
    Measure request elapsed time and store on request for logging.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        request._elapsed_start = start
        response = self.get_response(request)
        request._elapsed_ms = int((time.monotonic() - start) * 1000)
        return response
