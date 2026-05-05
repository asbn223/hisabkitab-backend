# apps/tenants/models.py
from django.db import models
from encrypted_model_fields.fields import EncryptedCharField, EncryptedEmailField

class Tenant(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    pan = EncryptedCharField(max_length=50, blank=True)
    vat_number = EncryptedCharField(max_length=50, blank=True)
    phone = EncryptedCharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    email = EncryptedEmailField(blank=True)  # ← Use EncryptedEmailField instead
    fiscal_year_start = models.IntegerField(
        default=4,
        help_text='Month number when fiscal year starts (4 = Shrawan)'
    )
    currency = models.CharField(max_length=3, default='NPR')
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenants_tenant'
        verbose_name = 'Tenant'
        verbose_name_plural = 'Tenants'
        indexes = [
            models.Index(fields=['slug', 'is_active']),
            models.Index(fields=['is_verified', 'created_at']),
        ]

    def __str__(self):
        return self.name

    def get_fiscal_year(self, bs_date=None):
        """Get current fiscal year details."""
        from core.bs_date import get_fiscal_year, get_current_bs_date
        if bs_date is None:
            bs_date = get_current_bs_date()
        return get_fiscal_year(bs_date, self.fiscal_year_start)


class TenantUser(models.Model):
    """
    User membership in a tenant.
    Links external auth users (Clerk/Auth0) to tenants.
    """
    ROLE_CHOICES = [
        ('owner', 'Owner'),  # Full control, can delete tenant
        ('admin', 'Admin'),  # Full control, cannot delete
        ('accountant', 'Accountant'),  # Can post transactions, manage books
        ('operator', 'Operator'),  # Can create invoices, receive payments
        ('viewer', 'Viewer'),  # Read-only access
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='users'
    )
    user_id = models.CharField(
        max_length=255,
        help_text='External auth provider user ID'
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)

    # Profile
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)

    # Status
    is_active = models.BooleanField(default=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenants_tenantuser'
        unique_together = [('tenant', 'user_id')]
        verbose_name = 'Tenant User'
        verbose_name_plural = 'Tenant Users'
        indexes = [
            models.Index(fields=['user_id', 'is_active']),
            models.Index(fields=['tenant', 'role']),
        ]

    def __str__(self):
        return f"{self.name or self.user_id} - {self.tenant.name}"

    def has_permission(self, permission):
        """Check if user has specific permission."""
        role_perms = {
            'owner': ['all'],
            'admin': ['all'],
            'accountant': ['view', 'create', 'edit', 'post_transactions', 'generate_reports'],
            'operator': ['view', 'create_invoices', 'record_payments'],
            'viewer': ['view'],
        }
        perms = role_perms.get(self.role, [])
        return 'all' in perms or permission in perms


class TenantSettings(models.Model):
    """
    Per-tenant configuration settings.
    """
    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name='settings'
    )

    # Invoice settings
    invoice_prefix = models.CharField(max_length=10, default='INV')
    invoice_starting_number = models.IntegerField(default=1)
    invoice_terms = models.TextField(
        default='Payment due within 30 days. Late payments subject to 2% monthly interest.',
        blank=True
    )

    # Print settings
    default_print_template = models.CharField(
        max_length=50,
        choices=[
            ('standard', 'Standard A4'),
            ('compact', 'Compact A4'),
            ('thermal80', 'Thermal 80mm'),
            ('thermal58', 'Thermal 58mm'),
        ],
        default='standard'
    )

    # Feature flags
    enable_inventory = models.BooleanField(default=True)
    enable_multi_currency = models.BooleanField(default=False)
    enable_api_access = models.BooleanField(default=False)

    # Integrations
    esewa_merchant_id = models.CharField(max_length=100, blank=True)
    khalti_public_key = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tenants_tenantsettings'

    def __str__(self):
        return f"Settings for {self.tenant.name}"