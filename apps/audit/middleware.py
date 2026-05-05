# apps/audit/middleware.py
import json
import threading

_local = threading.local()


class AuditLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Store request info for audit logging
        _local.request = request
        response = self.get_response(request)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        # Log API access
        pass


def get_current_request():
    return getattr(_local, 'request', None)