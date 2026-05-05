# apps/tenants/admin.py
from django.contrib import admin
from .models import Tenant, TenantUser, TenantSettings


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'pan', 'is_active', 'is_verified', 'created_at']
    list_filter = ['is_active', 'is_verified', 'created_at']
    search_fields = ['name', 'slug', 'pan', 'email']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'is_active', 'is_verified')
        }),
        ('Tax Information', {
            'fields': ('pan', 'vat_number'),
            'classes': ('collapse',)
        }),
        ('Contact', {
            'fields': ('address', 'phone', 'email'),
            'classes': ('collapse',)
        }),
        ('Fiscal Settings', {
            'fields': ('fiscal_year_start', 'currency'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(TenantUser)
class TenantUserAdmin(admin.ModelAdmin):
    list_display = ['user_id', 'tenant', 'role', 'name', 'is_active', 'joined_at']
    list_filter = ['role', 'is_active', 'joined_at']
    search_fields = ['user_id', 'name', 'email', 'tenant__name']
    readonly_fields = ['joined_at', 'updated_at']


@admin.register(TenantSettings)
class TenantSettingsAdmin(admin.ModelAdmin):
    list_display = ['tenant', 'invoice_prefix', 'enable_inventory', 'enable_api_access']
    search_fields = ['tenant__name']