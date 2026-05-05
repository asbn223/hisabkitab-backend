"""
Payment processing and gateway integration models.
Handles eSewa, Khalti, ConnectIPS, and bank reconciliations.
"""
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone

from apps.tenants.models import Tenant
from apps.accounts.models import Account, Transaction, LedgerEntry
from core.db.fields import FiscalDecimalField, BSDateField


class PaymentGateway(models.Model):
    """
    Configured payment gateways for a tenant.
    """
    GATEWAY_TYPES = [
        ('esewa', 'eSewa'),
        ('khalti', 'Khalti'),
        ('connectips', 'ConnectIPS'),
        ('fonepay', 'Fonepay'),
        ('hbl', 'HBL Payment Gateway'),
        ('bank', 'Direct Bank Transfer'),
        ('cash', 'Cash'),
        ('cheque', 'Cheque'),
    ]

    ENVIRONMENTS = [
        ('sandbox', 'Sandbox/Test'),
        ('production', 'Production/Live'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='payment_gateways'
    )

    gateway_type = models.CharField(
        max_length=20,
        choices=GATEWAY_TYPES
    )
    name = models.CharField(max_length=100)  # Display name
    is_active = models.BooleanField(default=True)
    environment = models.CharField(
        max_length=20,
        choices=ENVIRONMENTS,
        default='sandbox'
    )

    # Credentials (encrypted)
    merchant_id = models.CharField(max_length=255, blank=True)
    merchant_key = models.CharField(max_length=500, blank=True)  # Encrypted in production
    api_key = models.CharField(max_length=500, blank=True)
    api_secret = models.CharField(max_length=500, blank=True)

    # Configuration
    service_charge_percent = FiscalDecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00')
    )
    min_amount = FiscalDecimalField(default=Decimal('10.00'))
    max_amount = FiscalDecimalField(default=Decimal('1000000.00'))

    # Webhook settings
    webhook_secret = models.CharField(max_length=255, blank=True)
    webhook_url = models.URLField(blank=True)

    # Accounting link
    settlement_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gateway_settlements'
    )
    fee_expense_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gateway_fees'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payments_paymentgateway'
        unique_together = [('tenant', 'gateway_type', 'environment')]

    def __str__(self):
        return f"{self.name} ({self.get_gateway_type_display()})"


class PaymentTransaction(models.Model):
    """
    Individual payment transaction (initiated or received).
    """
    DIRECTION_CHOICES = [
        ('incoming', 'Incoming - Customer Payment'),
        ('outgoing', 'Outgoing - Supplier/Expense Payment'),
    ]

    STATUS_CHOICES = [
        ('initiated', 'Initiated'),  # Just created
        ('pending', 'Pending'),  # Waiting for gateway
        ('processing', 'Processing'),  # Gateway processing
        ('completed', 'Completed'),  # Success
        ('failed', 'Failed'),  # Failed/cancelled
        ('refunded', 'Refunded'),  # Full refund
        ('partial_refund', 'Partial Refund'),
        ('disputed', 'Disputed'),  # Chargeback/dispute
        ('settled', 'Settled'),  # Funds transferred to bank
    ]

    PAYMENT_METHODS = [
        ('esewa', 'eSewa Wallet'),
        ('khalti', 'Khalti Wallet'),
        ('connectips', 'ConnectIPS'),
        ('fonepay', 'Fonepay'),
        ('card', 'Credit/Debit Card'),
        ('bank_transfer', 'Bank Transfer'),
        ('cash', 'Cash'),
        ('cheque', 'Cheque'),
        ('wallet', 'Internal Wallet'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='payment_transactions'
    )

    # Identification
    transaction_id = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text='Internal transaction reference'
    )
    gateway = models.ForeignKey(
        PaymentGateway,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )

    # Transaction details
    direction = models.CharField(
        max_length=10,
        choices=DIRECTION_CHOICES,
        default='incoming'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='initiated',
        db_index=True
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHODS
    )

    # Amounts
    amount = FiscalDecimalField(
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    currency = models.CharField(max_length=3, default='NPR')
    exchange_rate = FiscalDecimalField(default=Decimal('1.0000'))

    # Fees (for incoming payments)
    gateway_fee = FiscalDecimalField(default=Decimal('0.0000'))
    service_charge = FiscalDecimalField(default=Decimal('0.0000'))
    net_amount = FiscalDecimalField(default=Decimal('0.0000'))

    # Parties
    customer_name = models.CharField(max_length=255, blank=True)
    customer_email = models.EmailField(blank=True)
    customer_phone = models.CharField(max_length=20, blank=True)
    customer_pan = models.CharField(max_length=20, blank=True)

    # Source document links
    source_type = models.CharField(
        max_length=50,
        blank=True,
        help_text='invoice, supplier_bill, salary, expense, etc.'
    )
    source_id = models.IntegerField(null=True, blank=True)
    source_number = models.CharField(max_length=100, blank=True)

    # Gateway specific
    gateway_transaction_id = models.CharField(max_length=255, blank=True, db_index=True)
    gateway_response_code = models.CharField(max_length=50, blank=True)
    gateway_response_message = models.TextField(blank=True)
    gateway_raw_response = models.JSONField(default=dict, blank=True)

    # URLs for redirection
    success_url = models.URLField(blank=True)
    failure_url = models.URLField(blank=True)
    cancel_url = models.URLField(blank=True)

    # Timestamps
    initiated_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    # Accounting
    transaction_entry = models.OneToOneField(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_transaction'
    )

    # Reconciliation
    is_reconciled = models.BooleanField(default=False)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    bank_statement_line = models.ForeignKey(
        'BankStatementLine',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_transactions'
    )

    # Metadata
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)  # Changed from initiated_at
    updated_at = models.DateTimeField(auto_now=True)  # Add this if needed

    class Meta:
        db_table = 'payments_paymenttransaction'
        indexes = [
            models.Index(fields=['tenant', 'status', 'created_at']),
            models.Index(fields=['tenant', 'gateway_transaction_id']),
            models.Index(fields=['tenant', 'source_type', 'source_id']),
            models.Index(fields=['tenant', 'is_reconciled']),
            models.Index(fields=['transaction_id']),
        ]
        ordering = ['-initiated_at']

    def __str__(self):
        return f"{self.transaction_id} - {self.amount}"

    def save(self, *args, **kwargs):
        if not self.transaction_id:
            self.transaction_id = self._generate_id()

        # Calculate net amount
        self.net_amount = self.amount - self.gateway_fee - self.service_charge
        super().save(*args, **kwargs)

    def _generate_id(self):
        """Generate unique transaction ID."""
        import uuid
        from datetime import datetime
        prefix = 'TXN'
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        unique = str(uuid.uuid4().int)[:6]
        return f"{prefix}-{timestamp}-{unique}"

    def complete(self, gateway_data=None):
        """Mark transaction as completed."""
        self.status = 'completed'
        self.completed_at = timezone.now()
        if gateway_data:
            self.gateway_raw_response = gateway_data
            self.gateway_transaction_id = gateway_data.get('transaction_id', '')
        self.save()

        # Create accounting entry
        self._create_accounting_entry()

        # Update source document
        self._update_source_document()

    def _create_accounting_entry(self):
        """Create double-entry for payment."""
        from apps.accounts.models import Transaction, LedgerEntry

        if self.transaction_entry:
            return

        tx = Transaction.objects.create(
            tenant=self.tenant,
            reference_number=self.transaction_id,
            date=timezone.now().date(),
            bs_date=self.tenant.get_fiscal_year()['current_date'],
            narration=f"Payment {self.payment_method} - {self.customer_name or self.source_number}",
            status='posted',
            source_type='payment',
            source_id=self.id,
            created_by=self.created_by
        )

        if self.direction == 'incoming':
            # Customer payment
            self._create_incoming_entry(tx)
        else:
            # Outgoing payment
            self._create_outgoing_entry(tx)

        self.transaction_entry = tx
        self.save(update_fields=['transaction_entry'])

    def _create_incoming_entry(self, tx):
        """Accounting entry for incoming payment."""
        from apps.accounts.models import LedgerEntry

        # Determine debit account (Gateway settlement or Cash/Bank)
        if self.gateway and self.gateway.settlement_account:
            debit_account = self.gateway.settlement_account
        else:
            debit_account = Account.objects.get(tenant=self.tenant, code='1000')

        # Credit Accounts Receivable or Income
        if self.source_type == 'invoice':
            ar_account = Account.objects.get(tenant=self.tenant, code='1200')
            credit_account = ar_account
        else:
            # Direct income
            credit_account = Account.objects.get(tenant=self.tenant, code='4100')

        # Debit the asset (Bank/Gateway)
        LedgerEntry.objects.create(
            tenant=self.tenant,
            transaction=tx,
            account=debit_account,
            debit=self.net_amount,
            credit=Decimal('0'),
            description=f"Payment received via {self.payment_method}"
        )

        # Record gateway fee if any
        if self.gateway_fee > 0:
            fee_account = self.gateway.fee_expense_account if self.gateway else \
                Account.objects.get(tenant=self.tenant, code='6200')  # Bank Charges
            LedgerEntry.objects.create(
                tenant=self.tenant,
                transaction=tx,
                account=fee_account,
                debit=self.gateway_fee,
                credit=Decimal('0'),
                description="Gateway fee"
            )

        # Credit AR or Income
        LedgerEntry.objects.create(
            tenant=self.tenant,
            transaction=tx,
            account=credit_account,
            debit=Decimal('0'),
            credit=self.amount,
            description=f"Payment from {self.customer_name}"
        )

        tx.total_debit = self.net_amount + self.gateway_fee
        tx.total_credit = self.amount
        tx.save()

    def _create_outgoing_entry(self, tx):
        """Accounting entry for outgoing payment."""
        from apps.accounts.models import LedgerEntry

        # Debit the expense/liability
        if self.source_type == 'supplier_bill':
            debit_account = Account.objects.get(tenant=self.tenant, code='2100')  # AP
        else:
            debit_account = Account.objects.get(tenant=self.tenant, code='5000')  # Expense

        # Credit Bank/Cash
        if self.gateway and self.gateway.settlement_account:
            credit_account = self.gateway.settlement_account
        else:
            credit_account = Account.objects.get(tenant=self.tenant, code='1000')

        LedgerEntry.objects.create(
            tenant=self.tenant,
            transaction=tx,
            account=debit_account,
            debit=self.amount,
            credit=Decimal('0'),
            description=f"Payment for {self.source_number}"
        )

        LedgerEntry.objects.create(
            tenant=self.tenant,
            transaction=tx,
            account=credit_account,
            debit=Decimal('0'),
            credit=self.amount,
            description=f"Paid via {self.payment_method}"
        )

        tx.total_debit = self.amount
        tx.total_credit = self.amount
        tx.save()

    def _update_source_document(self):
        """Update linked invoice or bill."""
        if self.source_type == 'invoice' and self.source_id:
            from apps.invoicing.models import Invoice, InvoicePayment
            try:
                invoice = Invoice.objects.get(id=self.source_id)
                InvoicePayment.objects.create(
                    tenant=self.tenant,
                    invoice=invoice,
                    date=timezone.now().date(),
                    bs_date=self.tenant.get_fiscal_year()['current_date'],
                    amount=self.amount,
                    method=self.payment_method,
                    gateway_transaction_id=self.gateway_transaction_id,
                    notes=f"Via {self.payment_method}"
                )
            except Invoice.DoesNotExist:
                pass

        elif self.source_type == 'supplier_bill' and self.source_id:
            from apps.purchases.models import SupplierBill, SupplierPayment
            try:
                bill = SupplierBill.objects.get(id=self.source_id)
                SupplierPayment.objects.create(
                    tenant=self.tenant,
                    supplier=bill.supplier,
                    bill=bill,
                    date=timezone.now().date(),
                    bs_date=self.tenant.get_fiscal_year()['current_date'],
                    amount=self.amount,
                    method=self.payment_method,
                    reference_number=self.gateway_transaction_id
                )
            except SupplierBill.DoesNotExist:
                pass


class PaymentRefund(models.Model):
    """
    Refund record for a payment transaction.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True
    )
    original_transaction = models.ForeignKey(
        PaymentTransaction,
        on_delete=models.CASCADE,
        related_name='refunds'
    )

    refund_id = models.CharField(max_length=100, unique=True)
    amount = FiscalDecimalField()
    reason = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )

    gateway_refund_id = models.CharField(max_length=255, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payments_paymentrefund'
        ordering = ['-created_at']


class BankAccount(models.Model):
    """
    Company bank accounts for reconciliation.
    """
    ACCOUNT_TYPES = [
        ('current', 'Current Account'),
        ('savings', 'Savings Account'),
        ('fixed', 'Fixed Deposit'),
        ('wallet', 'Digital Wallet'),
        ('foreign', 'Foreign Currency'),  # ✅ Fixed - added parentheses
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='bank_accounts'
    )

    account_name = models.CharField(max_length=255)
    bank_name = models.CharField(max_length=255)
    branch = models.CharField(max_length=255, blank=True)
    account_number = models.CharField(max_length=100)
    account_type = models.CharField(
        max_length=20,
        choices=ACCOUNT_TYPES,
        default='current'
    )

    # Currency
    currency = models.CharField(max_length=3, default='NPR')
    opening_balance = FiscalDecimalField(default=Decimal('0.0000'))
    current_balance = FiscalDecimalField(default=Decimal('0.0000'))

    # Accounting link
    ledger_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bank_account'
    )

    # For statement import
    statement_format = models.CharField(
        max_length=20,
        choices=[
            ('csv', 'CSV'),
            ('excel', 'Excel'),
            ('ofx', 'OFX'),
            ('mt940', 'MT940'),
            ('nabil', 'Nabil Bank'),
            ('nibl', 'NIBL'),
            ('sanima', 'Sanima Bank'),
            ('global_ime', 'Global IME'),
        ],
        default='csv'
    )

    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payments_bankaccount'
        unique_together = [('tenant', 'account_number')]

    def __str__(self):
        return f"{self.bank_name} - {self.account_number[-4:]}"

    def update_balance(self):
        """Recalculate balance from statements."""
        latest = BankStatementLine.objects.filter(
            account=self
        ).order_by('-date').first()

        if latest:
            self.current_balance = latest.running_balance
            self.save()


class BankStatement(models.Model):
    """
    Imported bank statement.
    """
    STATUS_CHOICES = [
        ('imported', 'Imported'),
        ('processing', 'Processing'),
        ('reconciled', 'Reconciled'),
        ('cancelled', 'Cancelled'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='bank_statements'
    )
    account = models.ForeignKey(
        BankAccount,
        on_delete=models.CASCADE,
        related_name='statements'
    )

    statement_date = models.DateField()
    start_date = models.DateField()
    end_date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='imported'
    )

    opening_balance = FiscalDecimalField()
    closing_balance = FiscalDecimalField()
    total_debits = FiscalDecimalField(default=Decimal('0.0000'))
    total_credits = FiscalDecimalField(default=Decimal('0.0000'))

    # File reference
    original_file = models.FileField(upload_to='statements/%Y/%m/', blank=True)
    import_log = models.TextField(blank=True)

    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payments_bankstatement'
        ordering = ['-statement_date']


class BankStatementLine(models.Model):
    """
    Individual line item from bank statement.
    """
    RECONCILE_STATUS = [
        ('unreconciled', 'Unreconciled'),
        ('matched', 'Auto-Matched'),
        ('manual', 'Manually Reconciled'),
        ('ignored', 'Ignored'),
    ]

    statement = models.ForeignKey(
        BankStatement,
        on_delete=models.CASCADE,
        related_name='lines'
    )
    account = models.ForeignKey(
        BankAccount,
        on_delete=models.CASCADE,
        related_name='statement_lines'
    )

    # Transaction details
    date = models.DateField(db_index=True)
    bs_date = BSDateField()
    description = models.TextField()
    reference = models.CharField(max_length=255, blank=True)

    # Amounts
    debit = FiscalDecimalField(default=Decimal('0.0000'))
    credit = FiscalDecimalField(default=Decimal('0.0000'))
    amount = FiscalDecimalField()  # Net amount (positive or negative)
    running_balance = FiscalDecimalField()

    # Reconciliation
    status = models.CharField(
        max_length=20,
        choices=RECONCILE_STATUS,
        default='unreconciled'
    )
    matched_transaction = models.ForeignKey(
        PaymentTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='statement_lines'
    )
    matched_invoice = models.ForeignKey(
        'invoicing.Invoice',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    matched_bill = models.ForeignKey(
        'purchases.SupplierBill',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # Suggestions (JSON for auto-match candidates)
    match_suggestions = models.JSONField(default=list, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'payments_bankstatementline'
        indexes = [
            models.Index(fields=['account', 'date', 'status']),
            models.Index(fields=['account', 'amount', 'status']),
            models.Index(fields=['statement', 'status']),
        ]
        ordering = ['date', 'id']

    def __str__(self):
        return f"{self.date} - {self.description[:50]} - {self.amount}"


class PaymentSettlement(models.Model):
    """
    Settlement batch from gateway to bank.
    """
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True
    )
    gateway = models.ForeignKey(
        PaymentGateway,
        on_delete=models.CASCADE,
        related_name='settlements'
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.CASCADE,
        related_name='settlements'
    )

    settlement_id = models.CharField(max_length=100, unique=True)
    settlement_date = models.DateField()

    # Amounts
    gross_amount = FiscalDecimalField()
    fee_amount = FiscalDecimalField(default=Decimal('0.0000'))
    net_amount = FiscalDecimalField()

    # Transactions included
    transaction_count = models.IntegerField()
    transactions = models.ManyToManyField(
        PaymentTransaction,
        related_name='settlements'
    )

    # Status
    is_reconciled = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payments_paymentsettlement'
        ordering = ['-settlement_date']