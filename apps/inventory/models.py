# apps/inventory/models.py
"""
Inventory and stock management models.
Supports FIFO, LIFO, and weighted average costing methods.
"""
from decimal import Decimal
from django.db import models

from apps.tenants.models import Tenant
from core.db.fields import FiscalDecimalField, BSDateField


class InventoryItem(models.Model):
    """
    Product/SKU master data.
    """
    VALUATION_METHODS = [
        ('fifo', 'FIFO - First In, First Out'),
        ('lifo', 'LIFO - Last In, First Out'),
        ('average', 'Weighted Average'),
        ('standard', 'Standard Cost'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True,
        related_name='inventory_items'
    )

    # Identification
    code = models.CharField(
        max_length=100,
        db_index=True,
        help_text='SKU or product code'
    )
    barcode = models.CharField(
        max_length=100,
        blank=True,
        db_index=True
    )
    name = models.CharField(max_length=255)
    name_nepali = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    # Classification
    category = models.CharField(max_length=100, blank=True, db_index=True)
    subcategory = models.CharField(max_length=100, blank=True)
    brand = models.CharField(max_length=100, blank=True)

    # Unit of measure
    unit = models.CharField(
        max_length=50,
        default='Pcs',
        help_text='Unit of measurement'
    )
    unit_nepali = models.CharField(max_length=50, blank=True)

    # Alternative units
    alternate_unit = models.CharField(max_length=50, blank=True)
    conversion_factor = FiscalDecimalField(
        default=Decimal('1.0000'),
        help_text='1 base unit = ? alternate units'
    )

    # VAT/Tax
    is_vat_applicable = models.BooleanField(default=False)
    vat_rate = FiscalDecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal('13.00')
    )
    vat_category = models.CharField(max_length=50, blank=True)

    # Pricing
    selling_price = FiscalDecimalField(
        default=Decimal('0.0000'),
        help_text='Standard selling price'
    )
    purchase_price = FiscalDecimalField(
        default=Decimal('0.0000'),
        help_text='Last purchase price / average cost'
    )
    standard_cost = FiscalDecimalField(
        default=Decimal('0.0000'),
        help_text='Standard cost for valuation'
    )
    min_selling_price = FiscalDecimalField(
        default=Decimal('0.0000'),
        help_text='Minimum allowed selling price'
    )
    max_discount_percent = FiscalDecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('100.00'),
        help_text='Maximum allowed discount %'
    )

    # Stock levels
    stock_quantity = FiscalDecimalField(
        default=Decimal('0.0000'),
        help_text='Current stock on hand'
    )
    reserved_quantity = FiscalDecimalField(
        default=Decimal('0.0000'),
        help_text='Reserved for orders'
    )
    available_quantity = FiscalDecimalField(
        default=Decimal('0.0000'),
        help_text='Available for sale (stock - reserved)'
    )
    reorder_level = FiscalDecimalField(
        default=Decimal('0.0000'),
        help_text='Reorder point'
    )
    reorder_quantity = FiscalDecimalField(
        default=Decimal('0.0000'),
        help_text='Suggested reorder quantity'
    )
    max_stock_level = FiscalDecimalField(
        default=Decimal('0.0000'),
        help_text='Maximum desired stock'
    )

    # Location
    warehouse_location = models.CharField(max_length=100, blank=True)
    bin_location = models.CharField(max_length=50, blank=True)

    # Valuation
    valuation_method = models.CharField(
        max_length=20,
        choices=VALUATION_METHODS,
        default='average'
    )

    # Dimensions & Weight
    weight_kg = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True
    )
    dimensions_cm = models.CharField(
        max_length=50,
        blank=True,
        help_text='LxWxH in cm'
    )

    # Status
    is_active = models.BooleanField(default=True)
    is_sellable = models.BooleanField(default=True)
    is_purchasable = models.BooleanField(default=True)
    track_inventory = models.BooleanField(
        default=True,
        help_text='If false, stock is not tracked (service items)'
    )

    # Accounting links
    sales_account = models.ForeignKey(
        'accounts.Account',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_sales_items'
    )
    purchase_account = models.ForeignKey(
        'accounts.Account',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_purchase_items'
    )
    inventory_account = models.ForeignKey(
        'accounts.Account',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_asset_items'
    )

    # Images
    image_url = models.URLField(max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'inventory_inventoryitem'
        unique_together = [('tenant', 'code')]
        indexes = [
            models.Index(fields=['tenant', 'category', 'is_active']),
            models.Index(fields=['tenant', 'is_active', 'stock_quantity']),
            models.Index(fields=['tenant', 'barcode']),
            models.Index(fields=['tenant', 'track_inventory', 'stock_quantity', 'reorder_level']),
        ]
        verbose_name = 'Inventory Item'
        verbose_name_plural = 'Inventory Items'
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"

    def save(self, *args, **kwargs):
        """Calculate available quantity."""
        self.available_quantity = self.stock_quantity - self.reserved_quantity
        if self.available_quantity < 0:
            self.available_quantity = Decimal('0')
        super().save(*args, **kwargs)

    def is_low_stock(self):
        """Check if stock is below reorder level."""
        if not self.track_inventory:
            return False
        return self.stock_quantity <= self.reorder_level

    def is_overstock(self):
        """Check if stock exceeds maximum."""
        if self.max_stock_level <= 0:
            return False
        return self.stock_quantity > self.max_stock_level

    def get_unit_cost(self):
        """Get current unit cost based on valuation method."""
        if self.valuation_method == 'standard':
            return self.standard_cost
        return self.purchase_price

    def get_stock_value(self):
        """Calculate total value of current stock."""
        return self.stock_quantity * self.get_unit_cost()


class StockMovement(models.Model):
    """
    Individual stock transaction (receipt, issue, adjustment).
    Immutable record - corrections create reversing entries.
    """
    MOVEMENT_TYPES = [
        ('receipt', 'Goods Receipt'),  # Stock in from purchase
        ('issue', 'Goods Issue'),  # Stock out to sale
        ('adjustment', 'Adjustment'),  # Stock count correction
        ('transfer_in', 'Transfer In'),  # From other location
        ('transfer_out', 'Transfer Out'),  # To other location
        ('return_in', 'Sales Return'),  # Customer return
        ('return_out', 'Purchase Return'),  # Return to supplier
        ('production_in', 'Production'),  # Manufactured
        ('production_out', 'Consumption'),  # Raw material use
        ('damage', 'Damage/Loss'),  # Write-off
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        db_index=True
    )
    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.CASCADE,
        related_name='movements'
    )

    # Movement details
    type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    quantity = FiscalDecimalField(
        help_text='Positive for in, negative for out (absolute value stored)'
    )
    unit_cost = FiscalDecimalField(
        null=True,
        blank=True,
        help_text='Cost per unit at time of movement'
    )
    total_cost = FiscalDecimalField(
        null=True,
        blank=True,
        help_text='Total cost (quantity * unit_cost)'
    )

    # Reference
    reference_type = models.CharField(
        max_length=50,
        blank=True,
        help_text='Source document type'
    )
    reference_id = models.IntegerField(
        null=True,
        blank=True,
        help_text='Source document ID'
    )
    reference_number = models.CharField(max_length=100, blank=True)

    # Dates
    date = models.DateField(db_index=True)
    bs_date = BSDateField()

    # Location
    from_location = models.CharField(max_length=100, blank=True)
    to_location = models.CharField(max_length=100, blank=True)

    # Batch/Serial
    batch_number = models.CharField(max_length=100, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    serial_number = models.CharField(max_length=100, blank=True)

    # Notes
    notes = models.TextField(blank=True)
    reason = models.CharField(max_length=255, blank=True)

    # Accounting link
    transaction = models.ForeignKey(
        'accounts.Transaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # Audit
    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'inventory_stockmovement'
        indexes = [
            models.Index(fields=['tenant', 'item', 'date']),
            models.Index(fields=['tenant', 'type', 'date']),
            models.Index(fields=['tenant', 'reference_type', 'reference_id']),
            models.Index(fields=['tenant', 'batch_number']),
            models.Index(fields=['item', 'expiry_date']),
        ]
        ordering = ['-date', '-created_at']

    def __str__(self):
        direction = 'IN' if self.quantity > 0 else 'OUT'
        return f"{direction} {abs(self.quantity)} {self.item.unit} {self.item.code}"

    def save(self, *args, **kwargs):
        """Calculate total cost if not provided."""
        if self.unit_cost and not self.total_cost:
            self.total_cost = abs(self.quantity) * self.unit_cost
        super().save(*args, **kwargs)


class StockReservation(models.Model):
    """
    Reserved stock for sales orders (soft hold).
    """
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE
    )
    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.CASCADE,
        related_name='reservations'
    )

    quantity = FiscalDecimalField()
    reserved_for_type = models.CharField(
        max_length=50,
        help_text='e.g., sales_order, production_order'
    )
    reserved_for_id = models.IntegerField()
    reserved_for_number = models.CharField(max_length=100, blank=True)

    # Status
    is_active = models.BooleanField(default=True)
    fulfilled_quantity = FiscalDecimalField(default=Decimal('0'))

    # Dates
    reserved_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'inventory_stockreservation'
        indexes = [
            models.Index(fields=['tenant', 'item', 'is_active']),
            models.Index(fields=['reserved_for_type', 'reserved_for_id']),
        ]

    @property
    def remaining_quantity(self):
        return self.quantity - self.fulfilled_quantity


class InventoryCount(models.Model):
    """
    Physical stock count / stock take.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='inventory_counts'
    )

    reference_number = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)

    # Scope
    category = models.CharField(max_length=100, blank=True)
    warehouse_location = models.CharField(max_length=100, blank=True)

    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft'
    )

    # Dates
    count_date = models.DateField()
    bs_count_date = BSDateField()
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_by = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'inventory_inventorycount'
        unique_together = [('tenant', 'reference_number')]


class InventoryCountLine(models.Model):
    """
    Individual line item in a stock count.
    """
    count = models.ForeignKey(
        InventoryCount,
        on_delete=models.CASCADE,
        related_name='lines'
    )
    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.CASCADE
    )

    # Quantities
    system_quantity = FiscalDecimalField(
        help_text='Quantity according to system'
    )
    counted_quantity = FiscalDecimalField(
        null=True,
        blank=True,
        help_text='Actual counted quantity'
    )
    difference = FiscalDecimalField(
        default=Decimal('0'),
        help_text='counted - system'
    )

    # Status
    is_counted = models.BooleanField(default=False)
    is_adjusted = models.BooleanField(default=False)

    # Notes
    notes = models.TextField(blank=True)
    counted_by = models.CharField(max_length=255, blank=True)
    counted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'inventory_inventorycountline'
        unique_together = [('count', 'item')]


class SupplierPriceList(models.Model):
    """
    Supplier-specific pricing for items.
    """
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE
    )
    supplier_id = models.IntegerField(db_index=True)
    item = models.ForeignKey(
        InventoryItem,
        on_delete=models.CASCADE,
        related_name='supplier_prices'
    )

    supplier_sku = models.CharField(max_length=100, blank=True)
    supplier_name = models.CharField(max_length=255, blank=True)

    # Pricing
    unit_price = FiscalDecimalField()
    min_order_qty = FiscalDecimalField(default=Decimal('1'))
    lead_time_days = models.IntegerField(default=7)

    # Validity
    valid_from = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    is_preferred = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'inventory_supplierpricelist'
        unique_together = [('tenant', 'supplier_id', 'item')]
        indexes = [
            models.Index(fields=['tenant', 'item', 'is_preferred']),
        ]