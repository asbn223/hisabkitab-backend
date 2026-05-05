"""
Invoicing models with VAT compliance for Nepal IRD.
Aligned with existing tenant, accounts, and inventory architecture.
"""
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator

from apps.tenants.models import Tenant
from apps.accounts.models import Account, Transaction, LedgerEntry
from apps.inventory.models import InventoryItem
from core.db.fields import FiscalDecimalField, BSDateField


class Customer(models.Model):
    """
    Customer master data for invoicing.
    """
    CUSTOMER_TYPES = [
        ('individual', 'Individual'),
        ('company', 'Company'),
        ('government', 'Government'),
        ('foreign', 'Foreign'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='customers'
    )

    # Identification
    code = models.CharField(max_length=50, blank=True, db_index=True)
    name = models.CharField(max_length=255)
    name_nepali = models.CharField(max_length=255, blank=True)

    # Type & Tax
    customer_type = models.CharField(
        max_length=20,
        choices=CUSTOMER_TYPES,
        default='company'
    )
    pan_number = models.CharField(max_length=20, blank=True, db_index=True)
    vat_registered = models.BooleanField(default=False)

    # Contact
    address = models.TextField(blank=True)
    address_nepali = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    contact_person = models.CharField(max_length=255, blank=True)

    # Credit terms
    credit_limit = FiscalDecimalField(default=Decimal('0.0000'))
    credit_days = models.IntegerField(default=30)
    default_discount_percent = FiscalDecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00')
    )

    # Accounting
    receivable_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_receivables'
    )

    # Status
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'invoicing_customer'
        unique_together = [('tenant', 'code')]
        indexes = [
            models.Index(fields=['tenant', 'pan_number']),
            models.Index(fields=['tenant', 'is_active', 'name']),
        ]
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code or 'No Code'})"

    def get_balance(self):
        """Calculate current receivable balance."""
        from django.db.models import Sum
        entries = LedgerEntry.objects.filter(
            tenant=self.tenant,
            account=self.receivable_account,
            transaction__status='posted'
        ).aggregate(
            debit=Sum('debit'),
            credit=Sum('credit')
        )
        debit = entries['debit'] or Decimal('0')
        credit = entries['credit'] or Decimal('0')
        # Debit balance = customer owes us
        return debit - credit


class Invoice(models.Model):
    """
    Sales Invoice with VAT compliance for Nepal IRD.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
        ('credit_note', 'Credit Note Issued'),
    ]

    INVOICE_TYPES = [
        ('tax', 'Tax Invoice'),  # 13% VAT - standard B2B
        ('retail', 'Retail Invoice'),  # Simplified B2C
        ('export', 'Export Invoice'),  # 0% VAT - international
        ('deemed', 'Deemed Export'),  # Special export category
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='invoices'
    )

    # Document numbering
    invoice_number = models.CharField(max_length=50, db_index=True)
    fiscal_year = models.CharField(max_length=10)  # 2080/81
    manual_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text='External PO number or reference'
    )

    # Type & Status
    invoice_type = models.CharField(
        max_length=20,
        choices=INVOICE_TYPES,
        default='tax'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        db_index=True
    )

    # Parties
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name='invoices'
    )
    # Snapshot at time of invoice (for historical accuracy)
    billed_name = models.CharField(max_length=255)
    billed_address = models.TextField(blank=True)
    billed_pan = models.CharField(max_length=20, blank=True)

    # Dates (Gregorian and BS)
    date = models.DateField(db_index=True)
    bs_date = BSDateField()
    due_date = models.DateField()
    bs_due_date = BSDateField()
    sent_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    # VAT Configuration
    is_vat_applicable = models.BooleanField(default=True)
    vat_rate = FiscalDecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('13.00'),
        help_text='Standard is 13% for Nepal'
    )

    # Amounts
    subtotal = FiscalDecimalField(default=Decimal('0.0000'))
    discount_amount = FiscalDecimalField(default=Decimal('0.0000'))
    discount_percent = FiscalDecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00')
    )

    # VAT Breakdown (IRD required)
    taxable_amount = FiscalDecimalField(default=Decimal('0.0000'))
    vat_amount = FiscalDecimalField(default=Decimal('0.0000'))
    exempt_amount = FiscalDecimalField(default=Decimal('0.0000'))
    zero_rated_amount = FiscalDecimalField(default=Decimal('0.0000'))

    total_amount = FiscalDecimalField(default=Decimal('0.0000'))
    amount_paid = FiscalDecimalField(default=Decimal('0.0000'))
    amount_due = FiscalDecimalField(default=Decimal('0.0000'))

    # IRD Integration
    ird_synced = models.BooleanField(default=False, db_index=True)
    ird_bill_id = models.CharField(max_length=100, blank=True)
    ird_qr_data = models.TextField(blank=True)
    ird_sync_error = models.TextField(blank=True)
    ird_synced_at = models.DateTimeField(null=True, blank=True)

    # Accounting link
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice'
    )

    # Metadata
    notes = models.TextField(blank=True)
    terms = models.TextField(blank=True)
    print_count = models.IntegerField(default=0)

    # Audit
    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'invoicing_invoice'
        unique_together = [('tenant', 'fiscal_year', 'invoice_number')]
        indexes = [
            models.Index(fields=['tenant', 'status', 'date']),
            models.Index(fields=['tenant', 'customer', 'status']),
            models.Index(fields=['tenant', 'due_date']),
            models.Index(fields=['tenant', 'ird_synced']),
        ]
        ordering = ['-date', '-invoice_number']

    def __str__(self):
        return f"INV-{self.invoice_number}"

    def save(self, *args, **kwargs):
        # Auto-generate invoice number if not provided
        if not self.invoice_number:
            self.invoice_number = self._generate_number()
        if not self.fiscal_year:
            self.fiscal_year = self.tenant.get_fiscal_year(self.bs_date)['year']

        # Calculate amount due
        self.amount_due = self.total_amount - self.amount_paid
        super().save(*args, **kwargs)

    def _generate_number(self):
        """Generate sequential invoice number."""
        prefix = "INV"
        fy = self.tenant.get_fiscal_year(self.bs_date)['year']
        fy_short = fy.replace('/', '')

        # Get count of invoices this FY
        count = Invoice.objects.filter(
            tenant=self.tenant,
            fiscal_year=fy
        ).count() + 1

        return f"{prefix}-{fy_short}-{count:05d}"

    def calculate_totals(self):
        """Recalculate all totals from line items."""
        lines = self.lines.all()

        self.subtotal = sum(line.line_total for line in lines)

        # Apply invoice-level discount
        if self.discount_percent > 0:
            self.discount_amount = self.subtotal * (self.discount_percent / 100)

        # Calculate VAT breakdown by type
        self.taxable_amount = sum(
            line.line_total - line.line_discount
            for line in lines
            if line.vat_type == 'standard' and line.vat_rate > 0
        )
        self.exempt_amount = sum(
            line.line_total - line.line_discount
            for line in lines
            if line.vat_type == 'exempt'
        )
        self.zero_rated_amount = sum(
            line.line_total - line.line_discount
            for line in lines
            if line.vat_type in ('zero_rated', 'export')
        )

        # VAT is calculated on discounted line amounts
        self.vat_amount = sum(line.vat_amount for line in lines)

        # Total after discount plus VAT
        self.total_amount = (self.subtotal - self.discount_amount) + self.vat_amount
        self.amount_due = self.total_amount - self.amount_paid

        self.save(update_fields=[
            'subtotal', 'discount_amount', 'taxable_amount', 'vat_amount',
            'exempt_amount', 'zero_rated_amount', 'total_amount', 'amount_due'
        ])

    def post_to_ledger(self):
        """Create double-entry accounting transaction."""
        if self.transaction:
            return  # Already posted

        from apps.accounts.models import Transaction, LedgerEntry

        # Determine accounts based on invoice type
        if self.invoice_type == 'export':
            sales_account_code = '4110'  # Export Sales
        elif self.invoice_type == 'retail':
            sales_account_code = '4101'  # Retail Sales
        else:
            sales_account_code = '4100'  # Domestic Sales

        # Get or create accounts
        ar_account = Account.objects.get(
            tenant=self.tenant,
            code='1200'  # Accounts Receivable
        )
        sales_account = Account.objects.get(
            tenant=self.tenant,
            code=sales_account_code
        )

        # Create transaction
        tx = Transaction.objects.create(
            tenant=self.tenant,
            reference_number=self.invoice_number,
            date=self.date,
            bs_date=self.bs_date,
            narration=f"Sales Invoice {self.invoice_number} - {self.customer.name}",
            status='draft',
            is_vat_applicable=self.is_vat_applicable,
            vat_amount=self.vat_amount,
            source_type='invoice',
            source_id=self.id,
            created_by=self.created_by
        )

        # 1. Debit Accounts Receivable (full amount customer owes)
        LedgerEntry.objects.create(
            tenant=self.tenant,
            transaction=tx,
            account=ar_account,
            debit=self.total_amount,
            credit=Decimal('0'),
            description=f"Receivable from {self.customer.name}"
        )

        # 2. Credit Sales (net of VAT if applicable)
        net_sales = self.taxable_amount + self.exempt_amount + self.zero_rated_amount - self.discount_amount
        if net_sales > 0:
            LedgerEntry.objects.create(
                tenant=self.tenant,
                transaction=tx,
                account=sales_account,
                debit=Decimal('0'),
                credit=net_sales,
                description="Sales revenue"
            )

        # 3. Credit VAT Output (liability)
        if self.vat_amount > 0:
            vat_account = Account.objects.get(
                tenant=self.tenant,
                code='2200'  # VAT Output
            )
            LedgerEntry.objects.create(
                tenant=self.tenant,
                transaction=tx,
                account=vat_account,
                debit=Decimal('0'),
                credit=self.vat_amount,
                description="VAT Output Tax"
            )

        # Update totals and post
        tx.total_debit = self.total_amount
        tx.total_credit = self.total_amount
        tx.status = 'posted'
        tx.posted_at = tx.created_at
        tx.posted_by = self.created_by
        tx.save()

        self.transaction = tx
        self.save(update_fields=['transaction'])

        # Reduce inventory for stock items
        for line in self.lines.filter(item__isnull=False, item__track_inventory=True):
            line.item.stock_quantity -= line.quantity
            line.item.save()

            # Create stock movement record
            from apps.inventory.models import StockMovement
            StockMovement.objects.create(
                tenant=self.tenant,
                item=line.item,
                type='issue',
                quantity=-line.quantity,
                unit_cost=line.unit_cost,
                total_cost=line.quantity * (line.unit_cost or Decimal('0')),
                reference_type='invoice',
                reference_id=self.id,
                reference_number=self.invoice_number,
                date=self.date,
                bs_date=self.bs_date,
                notes=f"Sold to {self.customer.name}",
                created_by=self.created_by
            )


class InvoiceLine(models.Model):
    """
    Individual line item on an invoice.
    """
    VAT_TYPES = [
        ('standard', 'Standard (13%)'),
        ('zero_rated', 'Zero Rated (0%)'),
        ('exempt', 'Exempt'),
        ('export', 'Export (0%)'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='lines'
    )
    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice_lines'
    )

    # Line details
    description = models.CharField(max_length=255)
    sku = models.CharField(max_length=50, blank=True)
    quantity = FiscalDecimalField(
        validators=[MinValueValidator(Decimal('0.0001'))]
    )
    unit = models.CharField(max_length=20, default='Pcs')

    # Pricing
    unit_price = FiscalDecimalField()
    unit_cost = FiscalDecimalField(
        null=True,
        blank=True,
        help_text='Cost at time of sale (for margin analysis)'
    )

    # Discounts
    discount_percent = FiscalDecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00')
    )
    line_discount = FiscalDecimalField(default=Decimal('0.0000'))

    # VAT
    vat_type = models.CharField(
        max_length=20,
        choices=VAT_TYPES,
        default='standard'
    )
    vat_rate = FiscalDecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('13.00')
    )

    # Calculated fields
    line_total = FiscalDecimalField(default=Decimal('0.0000'))
    vat_amount = FiscalDecimalField(default=Decimal('0.0000'))
    total_with_vat = FiscalDecimalField(default=Decimal('0.0000'))

    # Accounting
    revenue_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'invoicing_invoiceline'
        ordering = ['id']

    def save(self, *args, **kwargs):
        self._calculate()
        super().save(*args, **kwargs)

    def _calculate(self):
        """Calculate line totals."""
        # Gross amount
        gross = self.quantity * self.unit_price

        # Line discount
        if self.discount_percent > 0:
            self.line_discount = gross * (self.discount_percent / 100)

        # Net after discount
        net = gross - self.line_discount
        self.line_total = net

        # VAT calculation
        if self.vat_type == 'standard':
            self.vat_rate = Decimal('13.00')
            self.vat_amount = net * (self.vat_rate / 100)
        else:
            self.vat_rate = Decimal('0.00')
            self.vat_amount = Decimal('0.00')

        self.total_with_vat = net + self.vat_amount


class InvoicePayment(models.Model):
    """
    Payment received against an invoice.
    """
    PAYMENT_METHODS = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('esewa', 'eSewa'),
        ('khalti', 'Khalti'),
        ('connectips', 'ConnectIPS'),
        ('card', 'Card/Pos'),
        ('credit_note', 'Credit Note'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='payments'
    )

    # Payment details
    date = models.DateField()
    bs_date = BSDateField()
    amount = FiscalDecimalField()
    method = models.CharField(max_length=20, choices=PAYMENT_METHODS)

    # Bank/Account reference
    bank_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice_payments',
        limit_choices_to={'type': 'asset'}
    )
    reference_number = models.CharField(
        max_length=100,
        blank=True,
        help_text='Cheque number, transaction ID, etc.'
    )

    # Digital payment details
    gateway_transaction_id = models.CharField(max_length=255, blank=True)
    gateway_response = models.JSONField(default=dict, blank=True)

    # Notes
    notes = models.TextField(blank=True)

    # Accounting link
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoice_payment'
    )

    # Audit
    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'invoicing_invoicepayment'
        ordering = ['-date', '-created_at']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._update_invoice()
        self._create_ledger_entry()

    def _update_invoice(self):
        """Update invoice payment totals."""
        total_paid = sum(p.amount for p in self.invoice.payments.all())
        self.invoice.amount_paid = total_paid
        self.invoice.amount_due = self.invoice.total_amount - total_paid

        # Update status
        if self.invoice.amount_due <= 0:
            self.invoice.status = 'paid'
            self.invoice.paid_at = self.created_at
        elif self.invoice.amount_paid > 0:
            self.invoice.status = 'partial'

        self.invoice.save()

    def _create_ledger_entry(self):
        """Create accounting entry for payment."""
        if self.transaction:
            return

        from apps.accounts.models import Transaction, LedgerEntry

        # Determine debit account (Cash/Bank)
        if self.method == 'cash':
            debit_account = Account.objects.get(tenant=self.tenant, code='1000')
        elif self.bank_account:
            debit_account = self.bank_account
        else:
            # Default to cash if not specified
            debit_account = Account.objects.get(tenant=self.tenant, code='1000')

        ar_account = Account.objects.get(tenant=self.tenant, code='1200')

        tx = Transaction.objects.create(
            tenant=self.tenant,
            reference_number=f"PAY-{self.id}",
            date=self.date,
            bs_date=self.bs_date,
            narration=f"Payment for {self.invoice.invoice_number} - {self.method}",
            status='posted',
            source_type='invoice_payment',
            source_id=self.id,
            created_by=self.created_by
        )

        # Debit Cash/Bank
        LedgerEntry.objects.create(
            tenant=self.tenant,
            transaction=tx,
            account=debit_account,
            debit=self.amount,
            credit=Decimal('0')
        )

        # Credit Accounts Receivable
        LedgerEntry.objects.create(
            tenant=self.tenant,
            transaction=tx,
            account=ar_account,
            debit=Decimal('0'),
            credit=self.amount
        )

        tx.total_debit = self.amount
        tx.total_credit = self.amount
        tx.save()

        self.transaction = tx
        self.save(update_fields=['transaction'])


class CreditNote(models.Model):
    """
    Sales return / credit note against an invoice.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('applied', 'Applied'),
        ('cancelled', 'Cancelled'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True
    )
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='credit_notes'
    )

    credit_number = models.CharField(max_length=50, db_index=True)
    date = models.DateField()
    bs_date = BSDateField()

    # Amounts
    subtotal = FiscalDecimalField()
    vat_amount = FiscalDecimalField(default=Decimal('0.0000'))
    total_amount = FiscalDecimalField()

    # Reason
    REASONS = [
        ('return', 'Goods Return'),
        ('discount', 'Post-sale Discount'),
        ('error', 'Invoice Error'),
        ('damage', 'Damaged Goods'),
        ('other', 'Other'),
    ]
    reason = models.CharField(max_length=20, choices=REASONS)
    reason_notes = models.TextField(blank=True)

    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft'
    )

    # IRD sync (credit notes must also be reported)
    ird_synced = models.BooleanField(default=False)

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
        db_table = 'invoicing_creditnote'
        unique_together = [('tenant', 'credit_number')]

    def save(self, *args, **kwargs):
        if not self.credit_number:
            fy = self.invoice.fiscal_year
            fy_short = fy.replace('/', '')
            count = CreditNote.objects.filter(
                tenant=self.tenant,
                invoice__fiscal_year=fy
            ).count() + 1
            self.credit_number = f"CN-{fy_short}-{count:05d}"
        super().save(*args, **kwargs)