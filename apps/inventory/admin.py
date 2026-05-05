# apps/inventory/admin.py
from django.contrib import admin
from .models import (
    InventoryItem, StockMovement, StockReservation,
    InventoryCount, InventoryCountLine, SupplierPriceList
)


class StockMovementInline(admin.TabularInline):
    model = StockMovement
    extra = 0
    readonly_fields = ['created_at']
    fields = ['type', 'quantity', 'unit_cost', 'date', 'reference_type']


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = [
        'code', 'name', 'category', 'stock_quantity',
        'available_quantity', 'purchase_price', 'is_active'
    ]
    list_filter = ['category', 'is_active', 'is_vat_applicable', 'valuation_method']
    search_fields = ['code', 'name', 'barcode', 'description']
    readonly_fields = ['available_quantity', 'created_at', 'updated_at']
    inlines = [StockMovementInline]

    fieldsets = (
        (None, {
            'fields': ('tenant', 'code', 'barcode', 'name', 'name_nepali')
        }),
        ('Classification', {
            'fields': ('category', 'subcategory', 'brand', 'description'),
        }),
        ('Unit & Pricing', {
            'fields': ('unit', 'unit_nepali', 'selling_price', 'purchase_price', 'standard_cost'),
        }),
        ('Stock Levels', {
            'fields': ('stock_quantity', 'reserved_quantity', 'available_quantity',
                       'reorder_level', 'reorder_quantity', 'max_stock_level'),
        }),
        ('VAT/Tax', {
            'fields': ('is_vat_applicable', 'vat_rate'),
        }),
        ('Valuation', {
            'fields': ('valuation_method', 'track_inventory'),
        }),
        ('Status', {
            'fields': ('is_active', 'is_sellable', 'is_purchasable'),
        }),
    )


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ['item', 'type', 'quantity', 'unit_cost', 'date', 'reference_type']
    list_filter = ['type', 'date', 'tenant']
    search_fields = ['item__name', 'item__code', 'reference_number', 'batch_number']
    readonly_fields = ['created_at', 'total_cost']


@admin.register(InventoryCount)
class InventoryCountAdmin(admin.ModelAdmin):
    list_display = ['reference_number', 'description', 'status', 'count_date', 'created_by']
    list_filter = ['status', 'count_date']


@admin.register(SupplierPriceList)
class SupplierPriceListAdmin(admin.ModelAdmin):
    list_display = ['item', 'supplier_name', 'unit_price', 'lead_time_days', 'is_preferred']
    list_filter = ['is_preferred', 'tenant']