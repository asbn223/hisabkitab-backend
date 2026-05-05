# apps/tenants/services.py
"""
Business logic for tenant management.
"""
from .models import Tenant, TenantUser, TenantSettings


def create_tenant_with_owner(data, owner_user_id, owner_email='', owner_name=''):
    """
    Create new tenant with owner.

    Args:
        data: Tenant data dict
        owner_user_id: External auth user ID
        owner_email: Owner email
        owner_name: Owner name

    Returns:
        Created Tenant instance
    """
    from django.db import transaction
    from apps.accounts.services import seed_chart_of_accounts

    with transaction.atomic():
        # Create tenant
        tenant = Tenant.objects.create(**data)

        # Create owner membership
        TenantUser.objects.create(
            tenant=tenant,
            user_id=owner_user_id,
            role='owner',
            email=owner_email,
            name=owner_name,
        )

        # Create settings
        TenantSettings.objects.create(tenant=tenant)

        # Seed accounts
        seed_chart_of_accounts(tenant)

        return tenant


def get_user_tenants(user_id):
    """
    Get all tenants where user is member.

    Args:
        user_id: External auth user ID

    Returns:
        QuerySet of Tenant objects
    """
    tenant_ids = TenantUser.objects.filter(
        user_id=user_id,
        is_active=True
    ).values_list('tenant_id', flat=True)

    return Tenant.objects.filter(id__in=tenant_ids)


def can_user_access_tenant(user_id, tenant_id):
    """Check if user has access to tenant."""
    return TenantUser.objects.filter(
        user_id=user_id,
        tenant_id=tenant_id,
        is_active=True
    ).exists()