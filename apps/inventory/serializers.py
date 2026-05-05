# apps/inventory/serializers.py
"""
Serializers for inventory API.
"""
from rest_framework import serializers

from .models import (
    InventoryItem, StockMovement, StockReservation,
    InventoryCount, InventoryCountLine, SupplierPriceList
)


class InventoryItemListSerializer(serializers.ModelSerializer):
    """Minimal item info for lists."""

    stock_status = serializers.SerializerMethodField()
    stock_value = serializers.SerializerMethodField()

    class Meta:
        model = InventoryItem
        fields = [
            'id', 'code', 'barcode', 'name', 'category',
            'unit', 'stock_quantity', 'available_quantity',
            'selling_price', 'purchase_price',
            'is_active', 'stock_status',
            'stock_value', 'track_inventory'
        ]

    def get_stock_status(self, obj):
        if not obj.track_inventory:
            return 'not_tracked'
        if obj.is_low_stock():
            return 'low_stock'
        if obj.is_overstock():
            return 'overstock'
        return 'normal'

    def get_stock_value(self, obj):
        return str(obj.get_stock_value())


class InventoryItemDetailSerializer(serializers.ModelSerializer):
    """Full item details."""

    stock_status = serializers.SerializerMethodField()
    stock_value = serializers.SerializerMethodField()
    movements_count = serializers.SerializerMethodField()

    class Meta:
        model = InventoryItem
        exclude = ['tenant']
        read_only_fields = ['available_quantity', 'created_at', 'updated_at']

    def get_stock_status(self, obj):
        if not obj.track_inventory:
            return 'not_tracked'
        if obj.is_low_stock():
            return 'low_stock'
        if obj.is_overstock():
            return 'overstock'
        return 'normal'

    def get_stock_value(self, obj):
        return str(obj.get_stock_value())

    def get_movements_count(self, obj):
        return obj.movements.count()


class StockMovementSerializer(serializers.ModelSerializer):
    """Serializer for stock movements."""

    item_code = serializers.CharField(source='item.code', read_only=True)
    item_name = serializers.CharField(source='item.name', read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            'id', 'item', 'item_code', 'item_name',
            'type', 'quantity', 'unit_cost', 'total_cost',
            'reference_type', 'reference_id', 'reference_number',
            'date', 'bs_date', 'batch_number', 'expiry_date',
            'notes', 'created_at'
        ]
        read_only_fields = ['total_cost', 'created_at']

    def validate_quantity(self, value):
        if value == 0:
            raise serializers.ValidationError('Quantity cannot be zero.')
        return value


class StockAdjustmentSerializer(serializers.Serializer):
    """Serializer for stock adjustment request."""

    item_id = serializers.IntegerField()
    adjustment_qty = serializers.DecimalField(max_digits=20, decimal_places=4)
    unit_cost = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        required=False,
        allow_null=True
    )
    reason = serializers.CharField(max_length=255)
    date = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True)


class InventoryCountSerializer(serializers.ModelSerializer):
    """Serializer for stock counts."""

    line_count = serializers.SerializerMethodField()
    counted_lines = serializers.SerializerMethodField()

    class Meta:
        model = InventoryCount
        fields = [
            'id', 'reference_number', 'description',
            'category', 'warehouse_location',
            'status', 'count_date', 'bs_count_date',
            'line_count', 'counted_lines',
            'started_at', 'completed_at',
            'created_by', 'created_at'
        ]
        read_only_fields = ['bs_count_date', 'started_at', 'completed_at']

    def get_line_count(self, obj):
        return obj.lines.count()

    def get_counted_lines(self, obj):
        return obj.lines.filter(is_counted=True).count()


class InventoryCountLineSerializer(serializers.ModelSerializer):
    """Serializer for count lines."""

    item_code = serializers.CharField(source='item.code', read_only=True)
    item_name = serializers.CharField(source='item.name', read_only=True)
    item_unit = serializers.CharField(source='item.unit', read_only=True)

    class Meta:
        model = InventoryCountLine
        fields = [
            'id', 'item', 'item_code', 'item_name', 'item_unit',
            'system_quantity', 'counted_quantity', 'difference',
            'is_counted', 'is_adjusted', 'notes', 'counted_by', 'counted_at'
        ]


class StockReservationSerializer(serializers.ModelSerializer):
    """Serializer for reservations."""

    item_code = serializers.CharField(source='item.code', read_only=True)
    item_name = serializers.CharField(source='item.name', read_only=True)
    remaining = serializers.DecimalField(
        source='remaining_quantity',
        max_digits=20,
        decimal_places=4,
        read_only=True
    )

    class Meta:
        model = StockReservation
        fields = [
            'id', 'item', 'item_code', 'item_name',
            'quantity', 'fulfilled_quantity', 'remaining',
            'reserved_for_type', 'reserved_for_id', 'reserved_for_number',
            'is_active', 'reserved_at', 'expires_at'
        ]


class LowStockAlertSerializer(serializers.Serializer):
    """Serializer for low stock alerts."""

    item_id = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()
    current_stock = serializers.CharField()
    reorder_level = serializers.CharField()
    shortage = serializers.CharField()
    suggested_order = serializers.CharField()


class InventoryValuationSerializer(serializers.Serializer):
    """Serializer for inventory valuation report."""

    category = serializers.CharField()
    item_count = serializers.IntegerField()
    total_quantity = serializers.CharField()
    total_value = serializers.CharField()
    avg_unit_cost = serializers.CharField()


class SupplierPriceListSerializer(serializers.ModelSerializer):
    """Serializer for supplier prices."""

    item_code = serializers.CharField(source='item.code', read_only=True)
    item_name = serializers.CharField(source='item.name', read_only=True)

    class Meta:
        model = SupplierPriceList
        fields = [
            'id', 'item', 'item_code', 'item_name',
            'supplier_id', 'supplier_sku', 'supplier_name',
            'unit_price', 'min_order_qty', 'lead_time_days',
            'valid_from', 'valid_until', 'is_preferred'
        ]