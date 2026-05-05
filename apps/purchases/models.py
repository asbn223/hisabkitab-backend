"""
Purchase management models.
Handles procure-to-pay cycle: Requisitions, POs, GRN, Supplier Bills.
"""
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator

from apps.tenants.models import Tenant
from apps.accounts.models import Account, Transaction, LedgerEntry
from apps.inventory.models import InventoryItem, StockMovement
from core.db.fields import FiscalDecimalField, BSDateField


class Supplier(models.Model):
    """
    Supplier/Vendor master data.
    """
    SUPPLIER_TYPES = [
        ('local', 'Local Supplier'),
        ('import', 'Import/Foreign'),
        ('deemed', 'Deemed Supplier'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='suppliers'
    )

    # Identification
    code = models.CharField(max_length=50, blank=True, db_index=True)
    name = models.CharField(max_length=255)
    name_nepali = models.CharField(max_length=255, blank=True)
    legal_name = models.CharField(max_length=255, blank=True)

    # Tax
    pan_number = models.CharField(max_length=20, blank=True, db_index=True)
    vat_registered = models.BooleanField(default=False)
    supplier_type = models.CharField(
        max_length=20,
        choices=SUPPLIER_TYPES,
        default='local'
    )

    # Contact
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    contact_person = models.CharField(max_length=255, blank=True)

    # Credit terms
    credit_days = models.IntegerField(default=30)
    credit_limit = FiscalDecimalField(default=Decimal('0.0000'))

    # Accounting
    payable_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='supplier_payables'
    )

    # Status
    is_active = models.BooleanField(default=True)
    is_approved = models.BooleanField(default=False)

    # Bank details for payments
    bank_name = models.CharField(max_length=255, blank=True)
    bank_account = models.CharField(max_length=100, blank=True)
    bank_branch = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'purchases_supplier'
        unique_together = [('tenant', 'code')]
        indexes = [
            models.Index(fields=['tenant', 'pan_number']),
            models.Index(fields=['tenant', 'is_active', 'name']),
        ]
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code or 'No Code'})"

    def get_balance(self):
        """Calculate current payable balance."""
        from django.db.models import Sum
        entries = LedgerEntry.objects.filter(
            tenant=self.tenant,
            account=self.payable_account,
            transaction__status='posted'
        ).aggregate(
            debit=Sum('debit'),
            credit=Sum('credit')
        )
        credit = entries['credit'] or Decimal('0')
        debit = entries['debit'] or Decimal('0')
        # Credit balance = we owe supplier
        return credit - debit


class PurchaseRequisition(models.Model):
    """
    Internal request to purchase (optional approval workflow).
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('ordered', 'Converted to PO'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='requisitions'
    )

    requisition_number = models.CharField(max_length=50, db_index=True)
    date = models.DateField()
    bs_date = BSDateField()

    # Requester
    department = models.CharField(max_length=100, blank=True)
    requested_by = models.CharField(max_length=255, blank=True)

    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft'
    )

    # Totals
    total_amount = FiscalDecimalField(default=Decimal('0.0000'))

    # Approval
    approved_by = models.CharField(max_length=255, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'purchases_requisition'
        unique_together = [('tenant', 'requisition_number')]
        ordering = ['-date']

    def save(self, *args, **kwargs):
        if not self.requisition_number:
            fy = self.tenant.get_fiscal_year(self.bs_date)['year']
            fy_short = fy.replace('/', '')
            count = PurchaseRequisition.objects.filter(
                tenant=self.tenant,
                date__fiscal_year=fy
            ).count() + 1
            self.requisition_number = f"PR-{fy_short}-{count:05d}"
        super().save(*args, **kwargs)


class PurchaseRequisitionLine(models.Model):
    """
    Line items in a purchase requisition.
    """
    requisition = models.ForeignKey(
        PurchaseRequisition,
        on_delete=models.CASCADE,
        related_name='lines'
    )
    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.CASCADE
    )

    description = models.CharField(max_length=255, blank=True)
    quantity = FiscalDecimalField(
        validators=[MinValueValidator(Decimal('0.0001'))]
    )
    unit = models.CharField(max_length=20, default='Pcs')
    estimated_price = FiscalDecimalField(default=Decimal('0.0000'))
    total = FiscalDecimalField(default=Decimal('0.0000'))

    # Fulfillment tracking
    ordered_quantity = FiscalDecimalField(default=Decimal('0'))

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'purchases_requisitionline'

    def save(self, *args, **kwargs):
        self.total = self.quantity * self.estimated_price
        super().save(*args, **kwargs)


class PurchaseOrder(models.Model):
    """
    Purchase Order to supplier.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent', 'Sent to Supplier'),
        ('partial', 'Partially Received'),
        ('received', 'Fully Received'),
        ('billed', 'Billed'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ]

    ORDER_TYPES = [
        ('local', 'Local Purchase'),
        ('import', 'Import'),
        ('asset', 'Capital Purchase'),
        ('service', 'Service Order'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='purchase_orders'
    )

    # Document
    po_number = models.CharField(max_length=50, db_index=True)
    fiscal_year = models.CharField(max_length=10)
    date = models.DateField()
    bs_date = BSDateField()
    delivery_date = models.DateField(null=True, blank=True)
    bs_delivery_date = BSDateField(null=True, blank=True)

    # Type & Status
    order_type = models.CharField(
        max_length=20,
        choices=ORDER_TYPES,
        default='local'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft'
    )

    # Parties
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name='purchase_orders'
    )
    supplier_ref = models.CharField(
        max_length=100,
        blank=True,
        help_text='Supplier quotation or reference'
    )

    # Delivery
    delivery_location = models.TextField(blank=True)
    delivery_terms = models.CharField(max_length=255, blank=True)  # FOB, CIF, etc.

    # Financial
    currency = models.CharField(max_length=3, default='NPR')
    exchange_rate = FiscalDecimalField(default=Decimal('1.0000'))

    # VAT/Tax
    is_vat_applicable = models.BooleanField(default=True)
    vat_rate = FiscalDecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('13.00')
    )

    # Amounts
    subtotal = FiscalDecimalField(default=Decimal('0.0000'))
    discount_amount = FiscalDecimalField(default=Decimal('0.0000'))
    tax_amount = FiscalDecimalField(default=Decimal('0.0000'))  # Non-VAT taxes
    vat_amount = FiscalDecimalField(default=Decimal('0.0000'))
    shipping_cost = FiscalDecimalField(default=Decimal('0.0000'))
    total_amount = FiscalDecimalField(default=Decimal('0.0000'))

    # Tracking
    received_amount = FiscalDecimalField(default=Decimal('0.0000'))
    billed_amount = FiscalDecimalField(default=Decimal('0.0000'))

    # Links
    requisition = models.ForeignKey(
        PurchaseRequisition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='purchase_orders'
    )

    # Terms
    payment_terms = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    # Audit
    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'purchases_purchaseorder'
        unique_together = [('tenant', 'fiscal_year', 'po_number')]
        indexes = [
            models.Index(fields=['tenant', 'status', 'date']),
            models.Index(fields=['tenant', 'supplier', 'status']),
            models.Index(fields=['tenant', 'delivery_date']),
        ]
        ordering = ['-date', '-po_number']

    def __str__(self):
        return f"PO-{self.po_number}"

    def save(self, *args, **kwargs):
        if not self.po_number:
            self.po_number = self._generate_number()
        if not self.fiscal_year:
            self.fiscal_year = self.tenant.get_fiscal_year(self.bs_date)['year']
        super().save(*args, **kwargs)

    def _generate_number(self):
        fy = self.tenant.get_fiscal_year(self.bs_date)['year']
        fy_short = fy.replace('/', '')
        count = PurchaseOrder.objects.filter(
            tenant=self.tenant,
            fiscal_year=fy
        ).count() + 1
        return f"PO-{fy_short}-{count:05d}"

    def calculate_totals(self):
        """Recalculate PO totals."""
        lines = self.lines.all()

        self.subtotal = sum(line.line_total for line in lines)

        # VAT calculation
        taxable = sum(
            line.line_total for line in lines
            if line.vat_type == 'standard'
        )
        self.vat_amount = taxable * (self.vat_rate / 100) if self.is_vat_applicable else Decimal('0')

        self.total_amount = self.subtotal + self.vat_amount + self.shipping_cost - self.discount_amount

        self.save(update_fields=[
            'subtotal', 'vat_amount', 'total_amount',
            'received_amount', 'billed_amount'
        ])


class PurchaseOrderLine(models.Model):
    """
    Line items in a purchase order.
    """
    VAT_TYPES = [
        ('standard', 'Standard (13%)'),
        ('zero_rated', 'Zero Rated (0%)'),
        ('exempt', 'Exempt'),
        ('import', 'Import (0% but customs duty)'),
    ]

    po = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name='lines'
    )
    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    # Details
    description = models.CharField(max_length=255)
    specification = models.TextField(blank=True)
    quantity = FiscalDecimalField(
        validators=[MinValueValidator(Decimal('0.0001'))]
    )
    unit = models.CharField(max_length=20, default='Pcs')

    # Pricing
    unit_price = FiscalDecimalField()
    discount_percent = FiscalDecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00')
    )
    line_discount = FiscalDecimalField(default=Decimal('0.0000'))
    line_total = FiscalDecimalField(default=Decimal('0.0000'))

    # VAT
    vat_type = models.CharField(
        max_length=20,
        choices=VAT_TYPES,
        default='standard'
    )

    # Tracking
    received_quantity = FiscalDecimalField(default=Decimal('0'))
    billed_quantity = FiscalDecimalField(default=Decimal('0'))

    # Accounting
    expense_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'purchases_purchaseorderline'
        ordering = ['id']

    def save(self, *args, **kwargs):
        # Calculate totals
        gross = self.quantity * self.unit_price
        if self.discount_percent > 0:
            self.line_discount = gross * (self.discount_percent / 100)
        self.line_total = gross - self.line_discount
        super().save(*args, **kwargs)

    @property
    def pending_quantity(self):
        return self.quantity - self.received_quantity


class GoodsReceiptNote(models.Model):
    """
    GRN - Records physical receipt of goods.
    Can be partial receipt against PO.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('billed', 'Billed'),
        ('returned', 'Partially Returned'),
        ('cancelled', 'Cancelled'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='grns'
    )

    grn_number = models.CharField(max_length=50, db_index=True)
    fiscal_year = models.CharField(max_length=10)
    date = models.DateField()
    bs_date = BSDateField()

    # Reference
    po = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name='grns'
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name='grns'
    )
    supplier_delivery_note = models.CharField(max_length=100, blank=True)

    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft'
    )

    # Totals
    total_quantity = FiscalDecimalField(default=Decimal('0.0000'))
    total_amount = FiscalDecimalField(default=Decimal('0.0000'))

    # Inspection
    inspected_by = models.CharField(max_length=255, blank=True)
    inspection_notes = models.TextField(blank=True)

    # Accounting link
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='grn'
    )

    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'purchases_goodsreceiptnote'
        unique_together = [('tenant', 'fiscal_year', 'grn_number')]
        ordering = ['-date']

    def __str__(self):
        return f"GRN-{self.grn_number}"

    def save(self, *args, **kwargs):
        if not self.grn_number:
            fy = self.tenant.get_fiscal_year(self.bs_date)['year']
            fy_short = fy.replace('/', '')
            count = GoodsReceiptNote.objects.filter(
                tenant=self.tenant,
                fiscal_year=fy
            ).count() + 1
            self.grn_number = f"GRN-{fy_short}-{count:05d}"
        if not self.fiscal_year:
            self.fiscal_year = self.tenant.get_fiscal_year(self.bs_date)['year']
        super().save(*args, **kwargs)

    def confirm_receipt(self):
        """
        Confirm GRN and:
        1. Update inventory stock
        2. Update PO received quantities
        3. Create stock movements
        4. Post to ledger (Goods Received Not Invoiced)
        """
        if self.status != 'draft':
            return False

        for line in self.lines.all():
            po_line = line.po_line
            item = po_line.item

            if item and item.track_inventory:
                # Update stock
                item.stock_quantity += line.received_quantity
                item.purchase_price = line.unit_cost  # Update last purchase price
                item.save()

                # Create stock movement
                StockMovement.objects.create(
                    tenant=self.tenant,
                    item=item,
                    type='receipt',
                    quantity=line.received_quantity,
                    unit_cost=line.unit_cost,
                    total_cost=line.total_cost,
                    reference_type='grn',
                    reference_id=self.id,
                    reference_number=self.grn_number,
                    date=self.date,
                    bs_date=self.bs_date,
                    notes=f"GRN from {self.supplier.name}",
                    created_by=self.created_by
                )

            # Update PO line
            po_line.received_quantity += line.received_quantity
            po_line.save()

        # Update PO status
        po = self.po
        total_ordered = sum(l.quantity for l in po.lines.all())
        total_received = sum(l.received_quantity for l in po.lines.all())

        if total_received >= total_ordered:
            po.status = 'received'
        elif total_received > 0:
            po.status = 'partial'
        po.received_amount = sum(
            l.received_quantity * l.unit_price
            for l in po.lines.all()
        )
        po.save()

        # Create accounting entry (GRNI - Goods Received Not Invoiced)
        self._create_grni_entry()

        self.status = 'confirmed'
        self.save()
        return True

    def _create_grni_entry(self):
        """Create GRNI accounting entry."""
        from apps.accounts.models import Transaction, LedgerEntry

        grni_account, _ = Account.objects.get_or_create(
            tenant=self.tenant,
            code='1300',  # Goods Received Not Invoiced
            defaults={
                'name': 'GRNI',
                'type': 'asset',
                'is_system': True
            }
        )

        tx = Transaction.objects.create(
            tenant=self.tenant,
            reference_number=self.grn_number,
            date=self.date,
            bs_date=self.bs_date,
            narration=f"Goods receipt from {self.supplier.name}",
            status='posted',
            source_type='grn',
            source_id=self.id,
            created_by=self.created_by
        )

        total = sum(l.total_cost for l in self.lines.all())

        # Debit GRNI (asset)
        LedgerEntry.objects.create(
            tenant=self.tenant,
            transaction=tx,
            account=grni_account,
            debit=total,
            credit=Decimal('0')
        )

        # Credit GRNI Clearing (temporary liability)
        clearing_account, _ = Account.objects.get_or_create(
            tenant=self.tenant,
            code='2300',  # GRNI Clearing
            defaults={
                'name': 'GRNI Clearing',
                'type': 'liability',
                'is_system': True
            }
        )

        LedgerEntry.objects.create(
            tenant=self.tenant,
            transaction=tx,
            account=clearing_account,
            debit=Decimal('0'),
            credit=total
        )

        tx.total_debit = total
        tx.total_credit = total
        tx.save()

        self.transaction = tx
        self.save()


class GRNLine(models.Model):
    """
    Individual line in a GRN.
    """
    grn = models.ForeignKey(
        GoodsReceiptNote,
        on_delete=models.CASCADE,
        related_name='lines'
    )
    po_line = models.ForeignKey(
        PurchaseOrderLine,
        on_delete=models.CASCADE,
        related_name='grn_lines'
    )

    # Received quantities
    ordered_quantity = FiscalDecimalField()  # Snapshot from PO
    received_quantity = FiscalDecimalField(
        validators=[MinValueValidator(Decimal('0'))]
    )
    accepted_quantity = FiscalDecimalField(default=Decimal('0'))
    rejected_quantity = FiscalDecimalField(default=Decimal('0'))

    # Costing
    unit_cost = FiscalDecimalField()
    total_cost = FiscalDecimalField(default=Decimal('0.0000'))

    # Batch info
    batch_number = models.CharField(max_length=100, blank=True)
    expiry_date = models.DateField(null=True, blank=True)

    # Inspection
    quality_status = models.CharField(
        max_length=20,
        choices=[
            ('pass', 'Passed'),
            ('fail', 'Failed'),
            ('hold', 'On Hold'),
        ],
        default='pass'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'purchases_grnline'

    def save(self, *args, **kwargs):
        self.total_cost = self.received_quantity * self.unit_cost
        super().save(*args, **kwargs)


class SupplierBill(models.Model):
    """
    Supplier Invoice/Bill (Purchase Invoice).
    Can match multiple GRNs or direct (no GRN).
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ]

    BILL_TYPES = [
        ('goods', 'Goods Purchase'),
        ('services', 'Services'),
        ('expenses', 'Expenses'),
        ('asset', 'Capital Asset'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='supplier_bills'
    )

    bill_number = models.CharField(max_length=50, db_index=True)
    fiscal_year = models.CharField(max_length=10)

    # Supplier details
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        related_name='bills'
    )
    supplier_bill_number = models.CharField(max_length=100, blank=True)
    supplier_bill_date = models.DateField(null=True, blank=True)

    # Dates
    date = models.DateField()
    bs_date = BSDateField()
    due_date = models.DateField()
    bs_due_date = BSDateField()

    # Type & Status
    bill_type = models.CharField(
        max_length=20,
        choices=BILL_TYPES,
        default='goods'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft'
    )

    # References
    po = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bills'
    )
    grns = models.ManyToManyField(
        GoodsReceiptNote,
        blank=True,
        related_name='bills'
    )

    # VAT
    is_vat_applicable = models.BooleanField(default=True)
    vat_rate = FiscalDecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('13.00')
    )

    # Amounts
    subtotal = FiscalDecimalField(default=Decimal('0.0000'))
    discount_amount = FiscalDecimalField(default=Decimal('0.0000'))
    vat_amount = FiscalDecimalField(default=Decimal('0.0000'))
    total_amount = FiscalDecimalField(default=Decimal('0.0000'))

    amount_paid = FiscalDecimalField(default=Decimal('0.0000'))
    amount_due = FiscalDecimalField(default=Decimal('0.0000'))

    # TDS (Tax Deducted at Source) - Nepal requirement
    tds_applicable = models.BooleanField(default=False)
    tds_rate = FiscalDecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00')
    )
    tds_amount = FiscalDecimalField(default=Decimal('0.0000'))

    # Accounting
    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='supplier_bill'
    )

    notes = models.TextField(blank=True)

    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'purchases_supplierbill'
        unique_together = [('tenant', 'fiscal_year', 'bill_number')]
        indexes = [
            models.Index(fields=['tenant', 'status', 'due_date']),
            models.Index(fields=['tenant', 'supplier', 'status']),
        ]
        ordering = ['-date']

    def __str__(self):
        return f"BILL-{self.bill_number}"

    def save(self, *args, **kwargs):
        if not self.bill_number:
            fy = self.tenant.get_fiscal_year(self.bs_date)['year']
            fy_short = fy.replace('/', '')
            count = SupplierBill.objects.filter(
                tenant=self.tenant,
                fiscal_year=fy
            ).count() + 1
            self.bill_number = f"BILL-{fy_short}-{count:05d}"
        if not self.fiscal_year:
            self.fiscal_year = self.tenant.get_fiscal_year(self.bs_date)['year']

        self.amount_due = self.total_amount - self.amount_paid
        super().save(*args, **kwargs)

    def calculate_totals(self):
        """Calculate from lines."""
        lines = self.lines.all()
        self.subtotal = sum(line.line_total for line in lines)

        taxable = sum(
            line.line_total for line in lines
            if line.vat_type == 'standard'
        )
        self.vat_amount = taxable * (self.vat_rate / 100) if self.is_vat_applicable else Decimal('0')

        # TDS calculation (typically on services)
        if self.tds_applicable:
            self.tds_amount = self.subtotal * (self.tds_rate / 100)

        self.total_amount = self.subtotal + self.vat_amount - self.discount_amount - self.tds_amount
        self.amount_due = self.total_amount - self.amount_paid
        self.save()

    def confirm_bill(self):
        """Post to ledger and update GRN status."""
        if self.status != 'draft':
            return False

        from apps.accounts.models import Transaction, LedgerEntry

        # Get accounts
        payable_account = self.supplier.payable_account or Account.objects.get(
            tenant=self.tenant,
            code='2100'  # Accounts Payable
        )

        tx = Transaction.objects.create(
            tenant=self.tenant,
            reference_number=self.bill_number,
            date=self.date,
            bs_date=self.bs_date,
            narration=f"Supplier bill from {self.supplier.name} ({self.supplier_bill_number})",
            status='draft',
            is_vat_applicable=self.is_vat_applicable,
            vat_amount=self.vat_amount,
            source_type='supplier_bill',
            source_id=self.id,
            created_by=self.created_by
        )

        total = Decimal('0')

        # Debit appropriate accounts based on type
        for line in self.lines.all():
            if line.grn_line and line.grn_line.po_line.item:
                # Inventory purchase
                item = line.grn_line.po_line.item
                account = item.inventory_account or Account.objects.get(
                    tenant=self.tenant,
                    code='1500'  # Inventory
                )
            elif line.expense_account:
                account = line.expense_account
            else:
                # Default purchases
                account, _ = Account.objects.get_or_create(
                    tenant=self.tenant,
                    code='5000',
                    defaults={
                        'name': 'Purchases',
                        'type': 'expense',
                        'is_system': True
                    }
                )

            LedgerEntry.objects.create(
                tenant=self.tenant,
                transaction=tx,
                account=account,
                debit=line.line_total,
                credit=Decimal('0'),
                description=line.description
            )
            total += line.line_total

        # Debit VAT Input (asset - recoverable)
        if self.vat_amount > 0:
            vat_account, _ = Account.objects.get_or_create(
                tenant=self.tenant,
                code='1400',  # VAT Input
                defaults={
                    'name': 'VAT Input',
                    'type': 'asset',
                    'is_system': True
                }
            )
            LedgerEntry.objects.create(
                tenant=self.tenant,
                transaction=tx,
                account=vat_account,
                debit=self.vat_amount,
                credit=Decimal('0')
            )
            total += self.vat_amount

        # Credit Accounts Payable (net of TDS)
        net_payable = self.total_amount
        LedgerEntry.objects.create(
            tenant=self.tenant,
            transaction=tx,
            account=payable_account,
            debit=Decimal('0'),
            credit=net_payable
        )

        # Credit TDS Payable if applicable
        if self.tds_amount > 0:
            tds_account, _ = Account.objects.get_or_create(
                tenant=self.tenant,
                code='2210',  # TDS Payable
                defaults={
                    'name': 'TDS Payable',
                    'type': 'liability',
                    'is_system': True
                }
            )
            LedgerEntry.objects.create(
                tenant=self.tenant,
                transaction=tx,
                account=tds_account,
                debit=Decimal('0'),
                credit=self.tds_amount
            )

        # Post transaction
        tx.total_debit = total
        tx.total_credit = net_payable + self.tds_amount
        tx.status = 'posted'
        tx.posted_at = tx.created_at
        tx.posted_by = self.created_by
        tx.save()

        self.transaction = tx
        self.status = 'confirmed'
        self.save()

        # Update linked GRNs
        for grn in self.grns.all():
            grn.status = 'billed'
            grn.save()

        # Update PO billed amount
        if self.po:
            self.po.billed_amount = sum(b.total_amount for b in self.po.bills.all())
            if self.po.billed_amount >= self.po.total_amount:
                self.po.status = 'billed'
            self.po.save()

        return True


class SupplierBillLine(models.Model):
    """
    Line items in a supplier bill.
    Links to GRN lines for goods, or standalone for services.
    """
    bill = models.ForeignKey(
        SupplierBill,
        on_delete=models.CASCADE,
        related_name='lines'
    )
    grn_line = models.ForeignKey(
        GRNLine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    description = models.CharField(max_length=255)
    quantity = FiscalDecimalField(default=Decimal('1'))
    unit = models.CharField(max_length=20, default='Pcs')
    unit_price = FiscalDecimalField()
    line_total = FiscalDecimalField(default=Decimal('0.0000'))

    vat_type = models.CharField(
        max_length=20,
        choices=PurchaseOrderLine.VAT_TYPES,
        default='standard'
    )

    # For non-stock items
    expense_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'purchases_supplierbillline'

    def save(self, *args, **kwargs):
        self.line_total = self.quantity * self.unit_price
        super().save(*args, **kwargs)


class SupplierPayment(models.Model):
    """
    Payment made to supplier against bills.
    """
    PAYMENT_METHODS = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('esewa', 'eSewa'),
        ('khalti', 'Khalti'),
        ('connectips', 'ConnectIPS'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    bill = models.ForeignKey(
        SupplierBill,
        on_delete=models.CASCADE,
        related_name='payments'
    )

    date = models.DateField()
    bs_date = BSDateField()
    amount = FiscalDecimalField()
    method = models.CharField(max_length=20, choices=PAYMENT_METHODS)

    bank_account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    reference_number = models.CharField(max_length=100, blank=True)

    notes = models.TextField(blank=True)

    transaction = models.OneToOneField(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'purchases_supplierpayment'
        ordering = ['-date']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._update_bill()
        self._create_ledger_entry()

    def _update_bill(self):
        """Update bill payment status."""
        total_paid = sum(p.amount for p in self.bill.payments.all())
        self.bill.amount_paid = total_paid
        self.bill.amount_due = self.bill.total_amount - total_paid

        if self.bill.amount_due <= 0:
            self.bill.status = 'paid'
        else:
            self.bill.status = 'partial'
        self.bill.save()

    def _create_ledger_entry(self):
        """Create payment accounting entry."""
        if self.transaction:
            return

        from apps.accounts.models import Transaction, LedgerEntry

        payable_account = self.supplier.payable_account or Account.objects.get(
            tenant=self.tenant,
            code='2100'
        )

        if self.method == 'cash':
            bank_account = Account.objects.get(tenant=self.tenant, code='1000')
        else:
            bank_account = self.bank_account

        tx = Transaction.objects.create(
            tenant=self.tenant,
            reference_number=f"PAY-{self.id}",
            date=self.date,
            bs_date=self.bs_date,
            narration=f"Payment to {self.supplier.name} for {self.bill.bill_number}",
            status='posted',
            source_type='supplier_payment',
            source_id=self.id,
            created_by=self.created_by
        )

        # Debit Accounts Payable
        LedgerEntry.objects.create(
            tenant=self.tenant,
            transaction=tx,
            account=payable_account,
            debit=self.amount,
            credit=Decimal('0')
        )

        # Credit Bank/Cash
        LedgerEntry.objects.create(
            tenant=self.tenant,
            transaction=tx,
            account=bank_account,
            debit=Decimal('0'),
            credit=self.amount
        )

        tx.total_debit = self.amount
        tx.total_credit = self.amount
        tx.save()

        self.transaction = tx
        self.save(update_fields=['transaction'])