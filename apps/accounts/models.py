# apps/accounts/models.py
"""
Double-entry accounting models with fiscal compliance.
"""
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator

from apps.tenants.models import Tenant
from core.db.fields import FiscalDecimalField, BSDateField


class Account(models.Model):
    """
    Chart of Accounts entry.
    Supports hierarchical accounts (parent-child).
    """
    ACCOUNT_TYPES = [
        ('asset', 'Asset'),  # Debit increases, Credit decreases
        ('liability', 'Liability'),  # Credit increases, Debit decreases
        ('equity', 'Equity'),  # Credit increases, Debit decreases
        ('income', 'Income'),  # Credit increases (revenue)
        ('expense', 'Expense'),  # Debit increases (costs)
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='accounts'
    )
    code = models.CharField(
        max_length=50,
        db_index=True,
        help_text='Account code (e.g., 10101 for Cash)'
    )
    name = models.CharField(max_length=255)
    name_nepali = models.CharField(max_length=255, blank=True)

    type = models.CharField(
        max_length=20,
        choices=ACCOUNT_TYPES,
        db_index=True
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children'
    )

    # System accounts cannot be deleted (e.g., Cash, VAT accounts)
    is_system = models.BooleanField(
        default=False,
        help_text='System accounts cannot be deleted'
    )
    is_active = models.BooleanField(default=True)

    description = models.TextField(blank=True)

    # Opening balance at start of fiscal year
    # Positive = Debit balance, Negative = Credit balance
    opening_balance = FiscalDecimalField(
        default=Decimal('0.0000'),
        validators=[
            MinValueValidator(Decimal('-999999999999.9999')),
            MaxValueValidator(Decimal('999999999999.9999'))
        ]
    )

    # For bank accounts
    bank_name = models.CharField(max_length=255, blank=True)
    bank_account_number = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'accounts_account'
        unique_together = [('tenant', 'code')]
        indexes = [
            models.Index(fields=['tenant', 'type', 'is_active']),
            models.Index(fields=['tenant', 'parent', 'is_active']),
            models.Index(fields=['tenant', 'code', 'is_active']),
        ]
        verbose_name = 'Account'
        verbose_name_plural = 'Chart of Accounts'
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"

    def get_full_name(self):
        """Get full account name with parent."""
        if self.parent:
            return f"{self.parent.name} > {self.name}"
        return self.name

    def get_balance_type(self):
        """
        Get normal balance type for account.
        Returns 'debit' or 'credit'.
        """
        if self.type in ('asset', 'expense'):
            return 'debit'
        return 'credit'

    def get_current_balance(self, as_of_date=None):
        """
        Calculate current balance including all posted transactions.

        Args:
            as_of_date: Calculate balance as of this date (optional)

        Returns:
            Decimal balance (positive = debit, negative = credit)
        """
        from django.db.models import Sum

        entries = LedgerEntry.objects.filter(
            tenant=self.tenant,
            account=self,
            transaction__status='posted'
        )

        if as_of_date:
            entries = entries.filter(transaction__date__lte=as_of_date)

        sums = entries.aggregate(
            total_debit=Sum('debit'),
            total_credit=Sum('credit')
        )

        debit = sums['total_debit'] or Decimal('0')
        credit = sums['total_credit'] or Decimal('0')

        # Balance = Opening + Debits - Credits
        return self.opening_balance + debit - credit


class Transaction(models.Model):
    """
    Double-entry transaction (Journal Voucher).

    Each transaction must have equal debits and credits.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),  # Can be edited
        ('posted', 'Posted'),  # Immutable, affects balances
        ('cancelled', 'Cancelled'),  # Voided, no effect
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='transactions'
    )

    # Document reference
    reference_number = models.CharField(
        max_length=100,
        db_index=True,
        help_text='Unique transaction reference (e.g., JV-2024-00001)'
    )

    # Dates
    date = models.DateField(db_index=True)
    bs_date = BSDateField()

    # Description
    narration = models.TextField(help_text='Transaction description')

    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        db_index=True
    )

    # Totals (calculated on post)
    total_debit = FiscalDecimalField(default=Decimal('0.0000'))
    total_credit = FiscalDecimalField(default=Decimal('0.0000'))

    # VAT information
    is_vat_applicable = models.BooleanField(default=False)
    vat_amount = FiscalDecimalField(default=Decimal('0.0000'))

    # Audit
    created_by = models.CharField(max_length=255, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.CharField(max_length=255, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.CharField(max_length=255, blank=True)
    cancellation_reason = models.TextField(blank=True)

    # Source (for auto-generated transactions)
    source_type = models.CharField(
        max_length=50,
        blank=True,
        help_text='Source document type (e.g., invoice, purchase)'
    )
    source_id = models.IntegerField(
        null=True,
        blank=True,
        help_text='Source document ID'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'accounts_transaction'
        unique_together = [('tenant', 'reference_number')]
        indexes = [
            models.Index(fields=['tenant', 'date', 'status']),
            models.Index(fields=['tenant', 'status', 'created_at']),
            models.Index(fields=['tenant', 'source_type', 'source_id']),
        ]
        verbose_name = 'Transaction'
        verbose_name_plural = 'Transactions'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.reference_number} - {self.narration[:50]}"

    def is_balanced(self):
        """Check if debits equal credits."""
        from core.decimal.decimal_config import validate_double_entry
        return validate_double_entry(self.total_debit, self.total_credit)

    def can_edit(self):
        """Check if transaction can be edited."""
        return self.status == 'draft'

    def can_post(self):
        """Check if transaction can be posted."""
        if self.status != 'draft':
            return False

        # Must have entries
        if not self.entries.exists():
            return False

        # Must be balanced
        entries = self.entries.all()
        total_debit = sum(e.debit for e in entries)
        total_credit = sum(e.credit for e in entries)

        from core.decimal.decimal_config import fiscal_round
        return fiscal_round(total_debit) == fiscal_round(total_credit)


class LedgerEntry(models.Model):
    """
    Individual debit or credit entry in a transaction.

    The sum of all debits must equal sum of all credits in a transaction.
    """
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True
    )
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.CASCADE,
        related_name='entries',
        db_index=True
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.RESTRICT,  # Prevent deletion of accounts with entries
        related_name='ledger_entries'
    )

    # Amounts (one must be zero, other must be positive)
    debit = FiscalDecimalField(
        default=Decimal('0.0000'),
        help_text='Debit amount (positive number)'
    )
    credit = FiscalDecimalField(
        default=Decimal('0.0000'),
        help_text='Credit amount (positive number)'
    )

    # Additional description for this entry
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'accounts_ledgerentry'
        indexes = [
            models.Index(fields=['tenant', 'account', 'created_at']),
            models.Index(fields=['tenant', 'transaction', 'account']),
            models.Index(fields=['account', 'created_at']),
        ]
        verbose_name = 'Ledger Entry'
        verbose_name_plural = 'Ledger Entries'
        constraints = [
            # Ensure no negative amounts
            models.CheckConstraint(
                condition=models.Q(debit__gte=0),
                name='debit_non_negative',
                violation_error_message='Debit amount cannot be negative'
            ),
            models.CheckConstraint(
                condition=models.Q(credit__gte=0),
                name='credit_non_negative',
                violation_error_message='Credit amount cannot be negative'
            ),
            # Ensure at least one side has value
            models.CheckConstraint(
                condition=models.Q(debit__gt=0) | models.Q(credit__gt=0),
                name='debit_or_credit_required',
                violation_error_message='Either debit or credit must be greater than zero'
            ),
            # Ensure not both sides have value (single-sided entry)
            models.CheckConstraint(
                condition=~models.Q(debit__gt=0, credit__gt=0),
                name='not_both_debit_and_credit',
                violation_error_message='Cannot have both debit and credit in same entry'
            ),
        ]

    def __str__(self):
        if self.debit > 0:
            return f"Dr {self.debit} to {self.account.code}"
        return f"Cr {self.credit} to {self.account.code}"

    def get_amount(self):
        """Get amount regardless of side."""
        return self.debit if self.debit > 0 else self.credit

    def get_side(self):
        """Return 'debit' or 'credit'."""
        return 'debit' if self.debit > 0 else 'credit'


class FiscalYear(models.Model):
    """
    Fiscal year definition for a tenant.
    """
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='fiscal_years'
    )
    year_name = models.CharField(
        max_length=10,
        help_text='e.g., 2080/81'
    )
    start_date = BSDateField()
    end_date = BSDateField()
    is_closed = models.BooleanField(default=False)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.CharField(max_length=255, blank=True)

    # Retained earnings account for year-end closing
    retained_earnings_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'accounts_fiscalyear'
        unique_together = [('tenant', 'year_name')]
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.year_name} ({self.tenant.name})"

    def is_current(self):
        """Check if this is the current fiscal year."""
        from core.bs_date import get_current_bs_date
        today = get_current_bs_date()
        return self.start_date <= today <= self.end_date