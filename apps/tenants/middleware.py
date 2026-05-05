# apps/tenants/middleware.py
"""
Multi-tenancy middleware with PostgreSQL RLS.
"""
import threading
import logging
from django.db import connection
from django.http import Http404, JsonResponse
from django.core.exceptions import PermissionDenied

from .models import Tenant

logger = logging.getLogger('ledgersync')
_local = threading.local()


class TenantMiddleware:
    """
    Middleware to extract tenant from request and set RLS context.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip tenant check for admin and health endpoints
        if self._should_skip_tenant_check(request):
            return self.get_response(request)

        # Extract tenant
        tenant = self._get_tenant_from_request(request)

        if tenant:
            if not tenant.is_active:
                return JsonResponse(
                    {'error': 'Tenant is inactive'},
                    status=403
                )

            request.tenant = tenant
            _local.tenant = tenant

            # Set PostgreSQL RLS context
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL app.current_tenant = %s", [tenant.id])
            except Exception as e:
                logger.error(f"Failed to set RLS context: {e}")
                return JsonResponse(
                    {'error': 'Database configuration error'},
                    status=500
                )
        else:
            request.tenant = None
            _local.tenant = None

        # Process request
        response = self.get_response(request)

        # Clear RLS context
        if tenant:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL app.current_tenant = ''")
            except Exception as e:
                logger.warning(f"Failed to clear RLS context: {e}")

        # Add tenant header to response for debugging
        if settings.DEBUG and tenant:
            response['X-Tenant-ID'] = str(tenant.id)

        return response

    def _should_skip_tenant_check(self, request):
        """Check if request should skip tenant validation."""
        path = request.path_info

        # Skip admin, static, media, health check
        skip_prefixes = [
            '/admin/',
            '/static/',
            '/media/',
            '/__debug__/',
            '/health/',
            '/api/v1/auth/',
        ]

        for prefix in skip_prefixes:
            if path.startswith(prefix):
                return True

        return False

    def _get_tenant_from_request(self, request):
        """Extract tenant from request headers or subdomain."""
        # Priority: Header > Subdomain > Query param

        # Try header first
        tenant_id = request.headers.get('X-Tenant-ID')
        tenant_slug = request.headers.get('X-Tenant-Slug')

        if tenant_id:
            try:
                return Tenant.objects.get(id=int(tenant_id), is_active=True)
            except (Tenant.DoesNotExist, ValueError):
                pass

        if tenant_slug:
            try:
                return Tenant.objects.get(slug=tenant_slug, is_active=True)
            except Tenant.DoesNotExist:
                pass

        # Try subdomain (e.g., demo.ledgersync.com.np)
        host = request.get_host()
        if '.' in host:
            subdomain = host.split('.')[0]
            if subdomain not in ['www', 'api', 'app']:
                try:
                    return Tenant.objects.get(slug=subdomain, is_active=True)
                except Tenant.DoesNotExist:
                    pass

        # Try query parameter (for webhooks)
        tenant_id = request.GET.get('tenant_id')
        if tenant_id:
            try:
                return Tenant.objects.get(id=int(tenant_id), is_active=True)
            except (Tenant.DoesNotExist, ValueError):
                pass

        return None


def get_current_tenant():
    """Get current tenant from thread-local storage."""
    return getattr(_local, 'tenant', None)


def get_current_tenant_id():
    """Get current tenant ID."""
    tenant = get_current_tenant()
    return tenant.id if tenant else None


# Import settings at end to avoid circular import
from django.conf import settings