# apps/accounts/admin.py
from django.contrib import admin
from .models import Account, Transaction, LedgerEntry, FiscalYear


class LedgerEntryInline(admin.TabularInline):
    model = LedgerEntry
    extra = 2
    fields = ['account', 'debit', 'credit', 'description']
    autocomplete_fields = ['account']


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = [
        'code', 'name', 'type', 'parent',
        'opening_balance', 'is_system', 'is_active'
    ]
    list_filter = ['type', 'is_system', 'is_active', 'tenant']
    search_fields = ['code', 'name', 'name_nepali']
    autocomplete_fields = ['parent']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        (None, {
            'fields': ('tenant', 'code', 'name', 'name_nepali', 'type', 'parent')
        }),
        ('Balance', {
            'fields': ('opening_balance',),
        }),
        ('Bank Details', {
            'fields': ('bank_name', 'bank_account_number'),
            'classes': ('collapse',),
        }),
        ('Status', {
            'fields': ('is_system', 'is_active', 'description'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('parent', 'tenant')


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = [
        'reference_number', 'date', 'bs_date', 'narration',
        'status', 'total_debit', 'is_balanced'
    ]
    list_filter = ['status', 'date', 'tenant']
    search_fields = ['reference_number', 'narration']
    readonly_fields = [
        'total_debit', 'total_credit', 'created_at',
        'updated_at', 'posted_at', 'posted_by'
    ]
    inlines = [LedgerEntryInline]

    fieldsets = (
        (None, {
            'fields': ('tenant', 'reference_number', 'status')
        }),
        ('Dates', {
            'fields': ('date', 'bs_date'),
        }),
        ('Details', {
            'fields': ('narration', 'is_vat_applicable', 'vat_amount'),
        }),
        ('Totals', {
            'fields': ('total_debit', 'total_credit'),
            'classes': ('collapse',),
        }),
        ('Source', {
            'fields': ('source_type', 'source_id'),
            'classes': ('collapse',),
        }),
        ('Audit', {
            'fields': ('created_by', 'posted_at', 'posted_by'),
            'classes': ('collapse',),
        }),
    )

    def is_balanced(self, obj):
        return obj.is_balanced()

    is_balanced.boolean = True


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ['transaction', 'account', 'debit', 'credit', 'description']
    list_filter = ['account__type']
    search_fields = ['account__name', 'account__code', 'description']
    autocomplete_fields = ['transaction', 'account']


@admin.register(FiscalYear)
class FiscalYearAdmin(admin.ModelAdmin):
    list_display = ['year_name', 'tenant', 'start_date', 'end_date', 'is_closed']
    list_filter = ['is_closed', 'tenant']