"""
Tax compliance models for Nepal VAT and TDS.
Handles VAT returns, TDS deductions, and IRD reporting.
"""
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator

from apps.tenants.models import Tenant
from apps.accounts.models import Account, Transaction, LedgerEntry
from core.db.fields import FiscalDecimalField, BSDateField


class TaxPeriod(models.Model):
    """
    VAT/Tax filing period (monthly or quarterly).
    """
    PERIOD_TYPES = [
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('annual', 'Annual'),
    ]

    STATUS_CHOICES = [
        ('open', 'Open'),
        ('processing', 'Processing'),
        ('filed', 'Filed'),
        ('paid', 'Paid'),
        ('closed', 'Closed'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='tax_periods'
    )

    period_type = models.CharField(max_length=20, choices=PERIOD_TYPES, default='monthly')
    year_month = models.CharField(max_length=7)  # YYYY-MM format
    fiscal_year = models.CharField(max_length=10)  # 2080/81

    # Period dates
    start_date = models.DateField()
    end_date = models.DateField()
    bs_start_date = BSDateField()
    bs_end_date = BSDateField()

    # Due date for filing
    due_date = models.DateField()
    bs_due_date = BSDateField()

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')

    # Summary amounts (calculated)
    total_sales_vat = FiscalDecimalField(default=Decimal('0.0000'))
    total_purchase_vat = FiscalDecimalField(default=Decimal('0.0000'))
    vat_payable = FiscalDecimalField(default=Decimal('0.0000'))

    # TDS Summary
    tds_receivable = FiscalDecimalField(default=Decimal('0.0000'))  # TDS deducted by others
    tds_payable = FiscalDecimalField(default=Decimal('0.0000'))     # TDS we deducted

    # Filing details
    filed_at = models.DateTimeField(null=True, blank=True)
    filed_by = models.CharField(max_length=255, blank=True)
    acknowledgement_no = models.CharField(max_length=100, blank=True)

    # IRD sync
    ird_submitted = models.BooleanField(default=False)
    ird_submitted_at = models.DateTimeField(null=True, blank=True)
    ird_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tax_taxperiod'
        unique_together = [('tenant', 'year_month', 'period_type')]
        ordering = ['-year_month']

    def __str__(self):
        return f"{self.get_period_type_display()} - {self.year_month}"


class VATReturn(models.Model):
    """
    VAT Return form (Form 200 in Nepal).
    """
    RETURN_TYPES = [
        ('monthly', 'Monthly VAT Return'),
        ('quarterly', 'Quarterly VAT Return'),
        ('amended', 'Amended Return'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='vat_returns'
    )
    tax_period = models.OneToOneField(
        TaxPeriod,
        on_delete=models.CASCADE,
        related_name='vat_return'
    )

    return_type = models.CharField(max_length=20, choices=RETURN_TYPES, default='monthly')
    return_number = models.CharField(max_length=50, unique=True)

    # Part 1: Sales Details
    # Local sales
    local_taxable_sales = FiscalDecimalField(default=Decimal('0.0000'))
    local_vat_amount = FiscalDecimalField(default=Decimal('0.0000'))
    local_exempt_sales = FiscalDecimalField(default=Decimal('0.0000'))

    # Export sales
    export_zero_rated = FiscalDecimalField(default=Decimal('0.0000'))
    export_taxable = FiscalDecimalField(default=Decimal('0.0000'))

    # Part 2: Purchase Details
    local_taxable_purchases = FiscalDecimalField(default=Decimal('0.0000'))
    local_vat_paid = FiscalDecimalField(default=Decimal('0.0000'))
    import_vat = FiscalDecimalField(default=Decimal('0.0000'))
    exempt_purchases = FiscalDecimalField(default=Decimal('0.0000'))

    # Part 3: VAT Calculation
    vat_output = FiscalDecimalField(default=Decimal('0.0000'))  # Collected on sales
    vat_input = FiscalDecimalField(default=Decimal('0.0000'))   # Paid on purchases
    vat_credit_brought_forward = FiscalDecimalField(default=Decimal('0.0000'))
    vat_credit_carried_forward = FiscalDecimalField(default=Decimal('0.0000'))
    net_vat_payable = FiscalDecimalField(default=Decimal('0.0000'))

    # Part 4: Adjustments
    debit_notes_issued = FiscalDecimalField(default=Decimal('0.0000'))
    credit_notes_received = FiscalDecimalField(default=Decimal('0.0000'))
    adjustments = FiscalDecimalField(default=Decimal('0.0000'))

    # Status
    is_finalized = models.BooleanField(default=False)
    finalized_at = models.DateTimeField(null=True, blank=True)

    # IRD submission
    ird_reference = models.CharField(max_length=100, blank=True)
    ird_json_payload = models.JSONField(default=dict, blank=True)

    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tax_vatreturn'
        ordering = ['-created_at']

    def calculate_vat(self):
        """Calculate net VAT payable."""
        # Output VAT (sales)
        self.vat_output = self.local_vat_amount

        # Input VAT (purchases)
        self.vat_input = self.local_vat_paid + self.import_vat

        # Adjustments
        adjusted_output = self.vat_output - self.debit_notes_issued
        adjusted_input = self.vat_input - self.credit_notes_received

        # Net calculation
        net_vat = adjusted_output - adjusted_input - self.vat_credit_brought_forward

        if net_vat > 0:
            self.net_vat_payable = net_vat
            self.vat_credit_carried_forward = Decimal('0')
        else:
            self.net_vat_payable = Decimal('0')
            self.vat_credit_carried_forward = abs(net_vat)

        self.save()


class VATTransaction(models.Model):
    """
    Individual VAT-able transaction record for audit trail.
    Denormalized data from invoices and bills for quick reporting.
    """
    TRANSACTION_TYPES = [
        ('sale', 'Sales Invoice'),
        ('purchase', 'Purchase Bill'),
        ('debit_note', 'Debit Note'),
        ('credit_note', 'Credit Note'),
        ('import', 'Import'),
        ('adjustment', 'Adjustment'),
    ]

    VAT_TYPES = [
        ('standard', 'Standard (13%)'),
        ('zero_rated', 'Zero Rated'),
        ('exempt', 'Exempt'),
        ('non_vat', 'Non-VAT'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='vat_transactions'
    )
    tax_period = models.ForeignKey(
        TaxPeriod,
        on_delete=models.CASCADE,
        related_name='vat_transactions'
    )

    # Source document
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    source_id = models.IntegerField()
    source_number = models.CharField(max_length=100)
    source_date = models.DateField()

    # Party details
    party_name = models.CharField(max_length=255)
    party_pan = models.CharField(max_length=20, blank=True)
    party_address = models.TextField(blank=True)

    # VAT details
    vat_type = models.CharField(max_length=20, choices=VAT_TYPES, default='standard')
    vat_rate = FiscalDecimalField(default=Decimal('13.00'))

    # Amounts
    taxable_amount = FiscalDecimalField(default=Decimal('0.0000'))
    vat_amount = FiscalDecimalField(default=Decimal('0.0000'))
    total_amount = FiscalDecimalField(default=Decimal('0.0000'))

    # IRD specific
    ird_bill_id = models.CharField(max_length=100, blank=True)
    is_ird_synced = models.BooleanField(default=False)

    # Reconciliation
    is_reconciled = models.BooleanField(default=False)
    reconciliation_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tax_vattransaction'
        indexes = [
            models.Index(fields=['tenant', 'tax_period', 'transaction_type']),
            models.Index(fields=['tenant', 'source_date']),
            models.Index(fields=['party_pan', 'tax_period']),
        ]
        ordering = ['-source_date']


class TDSSection(models.Model):
    """
    TDS (Tax Deducted at Source) sections as per Nepal Income Tax Act.
    """
    SECTION_CHOICES = [
        ('88', 'Section 88 - Contract Payments'),
        ('89', 'Section 89 - Service Payments'),
        ('90', 'Section 90 - Interest/Dividend'),
        ('91', 'Section 91 - Rent'),
        ('92', 'Section 92 - Salary/Wages'),
        ('93', 'Section 93 - Consultation Fee'),
        ('94', 'Section 94 - Commission'),
        ('95', 'Section 95 - Royalty'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True
    )

    section_code = models.CharField(max_length=10, choices=SECTION_CHOICES)
    description = models.TextField()
    rate_percent = FiscalDecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00')
    )
    threshold_amount = FiscalDecimalField(
        default=Decimal('0.0000'),
        help_text='Amount above which TDS applies'
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'tax_tdssection'
        unique_together = [('tenant', 'section_code')]

    def __str__(self):
        return f"{self.section_code} - {self.get_section_code_display()}"


class TDSReturn(models.Model):
    """
    TDS return filing (Quarterly).
    """
    RETURN_TYPES = [
        ('92', 'Salary TDS - Section 92'),
        ('other', 'Other TDS - Section 88-91,93-95'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('filed', 'Filed'),
        ('paid', 'Tax Paid'),
        ('closed', 'Closed'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='tds_returns'
    )
    tax_period = models.ForeignKey(
        TaxPeriod,
        on_delete=models.CASCADE,
        related_name='tds_returns'
    )

    return_type = models.CharField(max_length=10, choices=RETURN_TYPES)
    return_number = models.CharField(max_length=50, unique=True)

    # Summary
    total_deducted = FiscalDecimalField(default=Decimal('0.0000'))
    total_deposit = FiscalDecimalField(default=Decimal('0.0000'))
    interest_penalty = FiscalDecimalField(default=Decimal('0.0000'))
    total_payable = FiscalDecimalField(default=Decimal('0.0000'))

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')

    # Filing details
    filed_at = models.DateTimeField(null=True, blank=True)
    filed_by = models.CharField(max_length=255, blank=True)
    ird_acknowledgement = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tax_tdsreturn'
        unique_together = [('tenant', 'tax_period', 'return_type')]


class TDSDeduction(models.Model):
    """
    Individual TDS deduction record.
    """
    DEDUCTION_TYPES = [
        ('payment', 'Payment to Supplier'),
        ('salary', 'Salary Payment'),
        ('contract', 'Contract Payment'),
        ('service', 'Service Payment'),
        ('interest', 'Interest Payment'),
        ('rent', 'Rent Payment'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='tds_deductions'
    )
    tds_section = models.ForeignKey(
        TDSSection,
        on_delete=models.PROTECT,
        related_name='deductions'
    )

    # Source document
    source_type = models.CharField(max_length=50)  # supplier_bill, invoice, salary
    source_id = models.IntegerField()
    document_number = models.CharField(max_length=100)
    date = models.DateField()
    bs_date = BSDateField()

    # Party details
    party_name = models.CharField(max_length=255)
    party_pan = models.CharField(max_length=20, blank=True)
    party_address = models.TextField(blank=True)

    # Amounts
    base_amount = FiscalDecimalField()  # Amount before TDS
    tds_rate = FiscalDecimalField(max_digits=5, decimal_places=2)
    tds_amount = FiscalDecimalField()
    net_amount = FiscalDecimalField()  # Amount after TDS deduction

    # Status
    is_deposited = models.BooleanField(default=False)
    deposited_date = models.DateField(null=True, blank=True)
    deposit_voucher_no = models.CharField(max_length=100, blank=True)

    # TDS Return link
    tds_return = models.ForeignKey(
        TDSReturn,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deductions'
    )

    # Accounting
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tax_tdsdeduction'
        indexes = [
            models.Index(fields=['tenant', 'date', 'is_deposited']),
            models.Index(fields=['party_pan', 'date']),
            models.Index(fields=['tds_return']),
        ]
        ordering = ['-date']

    def save(self, *args, **kwargs):
        if not self.tds_amount:
            self.tds_amount = self.base_amount * (self.tds_rate / 100)
        if not self.net_amount:
            self.net_amount = self.base_amount - self.tds_amount
        super().save(*args, **kwargs)


class TaxDeposit(models.Model):
    """
    Tax deposits to IRD (VAT, TDS, Income Tax).
    """
    TAX_TYPES = [
        ('vat', 'VAT'),
        ('tds_salary', 'TDS - Salary'),
        ('tds_other', 'TDS - Other'),
        ('income_tax', 'Income Tax'),
        ('excise', 'Excise Duty'),
        ('customs', 'Customs Duty'),
    ]

    PAYMENT_MODES = [
        ('online', 'Online Banking'),
        ('voucher', 'Bank Voucher'),
        ('cheque', 'Cheque'),
        ('cash', 'Cash'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='tax_deposits'
    )

    deposit_number = models.CharField(max_length=50, unique=True)
    tax_type = models.CharField(max_length=20, choices=TAX_TYPES)

    # Period reference
    tax_period = models.ForeignKey(
        TaxPeriod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # Amounts
    principal_amount = FiscalDecimalField()
    interest_amount = FiscalDecimalField(default=Decimal('0.0000'))
    penalty_amount = FiscalDecimalField(default=Decimal('0.0000'))
    total_amount = FiscalDecimalField()

    # Deposit details
    date = models.DateField()
    bs_date = BSDateField()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODES)

    # Bank details
    bank_name = models.CharField(max_length=255, blank=True)
    bank_voucher_no = models.CharField(max_length=100, blank=True)
    ird_reference = models.CharField(max_length=100, blank=True)

    # Links
    vat_return = models.ForeignKey(
        VATReturn,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    tds_return = models.ForeignKey(
        TDSReturn,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # Accounting
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    notes = models.TextField(blank=True)
    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tax_taxdeposit'
        ordering = ['-date']

    def save(self, *args, **kwargs):
        self.total_amount = self.principal_amount + self.interest_amount + self.penalty_amount
        super().save(*args, **kwargs)


class TaxCertificate(models.Model):
    """
    TDS Certificates (Form 2076 in Nepal) issued to deductees.
    """
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='tax_certificates'
    )

    certificate_number = models.CharField(max_length=50, unique=True)
    tds_deduction = models.OneToOneField(
        TDSDeduction,
        on_delete=models.CASCADE,
        related_name='certificate'
    )

    # Certificate details
    issue_date = models.DateField()
    bs_issue_date = BSDateField()
    fiscal_year = models.CharField(max_length=10)

    # Party details (snapshot)
    party_name = models.CharField(max_length=255)
    party_pan = models.CharField(max_length=20)
    party_address = models.TextField(blank=True)

    # Amounts
    amount_paid = FiscalDecimalField()
    tax_deducted = FiscalDecimalField()

    # Status
    is_downloaded = models.BooleanField(default=False)
    downloaded_at = models.DateTimeField(null=True, blank=True)
    downloaded_by = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tax_taxcertificate'
        ordering = ['-issue_date']


class TaxConfig(models.Model):
    """
    Tax configuration for tenant.
    """
    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        related_name='tax_config'
    )

    # VAT settings
    vat_registration_date = models.DateField(null=True, blank=True)
    is_vat_registered = models.BooleanField(default=False)
    default_vat_rate = FiscalDecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('13.00')
    )
    vat_filing_frequency = models.CharField(
        max_length=20,
        choices=[('monthly', 'Monthly'), ('quarterly', 'Quarterly')],
        default='monthly'
    )

    # TDS settings
    pan_number = models.CharField(max_length=20, blank=True)
    tds_filing_frequency = models.CharField(
        max_length=20,
        choices=[('monthly', 'Monthly'), ('quarterly', 'Quarterly')],
        default='monthly'
    )

    # Accounting links
    vat_output_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vat_output_config'
    )
    vat_input_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vat_input_config'
    )
    tds_payable_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tds_payable_config'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tax_taxconfig'