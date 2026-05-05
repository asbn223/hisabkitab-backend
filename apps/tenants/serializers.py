# apps/tenants/serializers.py
"""
Serializers for tenant API.
"""
from rest_framework import serializers
from .models import Tenant, TenantUser, TenantSettings


class TenantListSerializer(serializers.ModelSerializer):
    """Minimal serializer for list views."""

    class Meta:
        model = Tenant
        fields = ['id', 'name', 'slug', 'currency', 'is_active']


class TenantDetailSerializer(serializers.ModelSerializer):
    """Full serializer with sensitive data."""

    fiscal_year = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            'id', 'name', 'slug', 'pan', 'vat_number',
            'address', 'phone', 'email',
            'fiscal_year_start', 'currency', 'fiscal_year',
            'is_active', 'is_verified',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'is_verified']

    def get_fiscal_year(self, obj):
        """Get current fiscal year."""
        return obj.get_fiscal_year()


class TenantCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new tenant."""

    class Meta:
        model = Tenant
        fields = ['name', 'slug', 'pan', 'vat_number', 'address',
                  'phone', 'email', 'fiscal_year_start', 'currency']

    def validate_slug(self, value):
        """Ensure slug is URL-safe."""
        import re
        if not re.match(r'^[a-z0-9-]+$', value):
            raise serializers.ValidationError(
                'Slug must contain only lowercase letters, numbers, and hyphens.'
            )
        if len(value) < 3:
            raise serializers.ValidationError('Slug must be at least 3 characters.')
        return value


class TenantUserSerializer(serializers.ModelSerializer):
    """Serializer for tenant users."""

    tenant_name = serializers.CharField(source='tenant.name', read_only=True)

    class Meta:
        model = TenantUser
        fields = [
            'id', 'tenant', 'tenant_name', 'user_id', 'role',
            'name', 'email', 'phone', 'is_active',
            'joined_at', 'last_login_at'
        ]
        read_only_fields = ['id', 'joined_at', 'last_login_at']


class TenantSettingsSerializer(serializers.ModelSerializer):
    """Serializer for tenant settings."""

    class Meta:
        model = TenantSettings
        fields = [
            'invoice_prefix', 'invoice_starting_number', 'invoice_terms',
            'default_print_template',
            'enable_inventory', 'enable_multi_currency', 'enable_api_access',
            'esewa_merchant_id', 'khalti_public_key'
        ]