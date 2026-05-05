# apps/tenants/permissions.py
"""
DRF permissions for multi-tenant access control.
"""
from rest_framework import permissions


class TenantPermission(permissions.BasePermission):
    """
    Base permission that checks for valid tenant and user membership.
    """

    def has_permission(self, request, view):
        # Superusers bypass all checks
        if request.user.is_superuser:
            return True

        # Check tenant is set
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return False

        # Check user is member of tenant
        from .models import TenantUser
        return TenantUser.objects.filter(
            tenant=tenant,
            user_id=request.user.id,
            is_active=True
        ).exists()


class IsTenantOwner(permissions.BasePermission):
    """Only tenant owners can access."""

    def has_permission(self, request, view):
        if request.user.is_superuser:
            return True

        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return False

        from .models import TenantUser
        return TenantUser.objects.filter(
            tenant=tenant,
            user_id=request.user.id,
            role='owner',
            is_active=True
        ).exists()


class IsTenantAdmin(permissions.BasePermission):
    """Tenant owners and admins can access."""

    def has_permission(self, request, view):
        if request.user.is_superuser:
            return True

        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return False

        from .models import TenantUser
        return TenantUser.objects.filter(
            tenant=tenant,
            user_id=request.user.id,
            role__in=['owner', 'admin'],
            is_active=True
        ).exists()


class IsAccountant(permissions.BasePermission):
    """Accountants and above can access."""

    def has_permission(self, request, view):
        if request.user.is_superuser:
            return True

        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return False

        from .models import TenantUser
        return TenantUser.objects.filter(
            tenant=tenant,
            user_id=request.user.id,
            role__in=['owner', 'admin', 'accountant'],
            is_active=True
        ).exists()


class CanPostTransactions(permissions.BasePermission):
    """Specific permission for posting transactions."""

    def has_permission(self, request, view):
        if request.user.is_superuser:
            return True

        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return False

        from .models import TenantUser
        user = TenantUser.objects.filter(
            tenant=tenant,
            user_id=request.user.id,
            is_active=True
        ).first()

        if not user:
            return False

        return user.has_permission('post_transactions')