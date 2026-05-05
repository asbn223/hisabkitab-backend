from rest_framework import serializers
from .models import Customer, Invoice, InvoiceLine, InvoicePayment, CreditNote
from apps.inventory.models import InventoryItem


class CustomerSerializer(serializers.ModelSerializer):
    balance = serializers.DecimalField(
        max_digits=15,
        decimal_places=4,
        source='get_balance',
        read_only=True
    )

    class Meta:
        model = Customer
        fields = [
            'id', 'code', 'name', 'name_nepali', 'customer_type',
            'pan_number', 'vat_registered', 'address', 'phone', 'email',
            'credit_limit', 'credit_days', 'receivable_account',
            'is_active', 'balance', 'created_at'
        ]


class InvoiceLineSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)

    class Meta:
        model = InvoiceLine
        fields = [
            'id', 'item', 'item_name', 'description', 'sku',
            'quantity', 'unit', 'unit_price', 'unit_cost',
            'discount_percent', 'line_discount',
            'vat_type', 'vat_rate', 'vat_amount',
            'line_total', 'total_with_vat',
            'revenue_account'
        ]
        read_only_fields = [
            'line_discount', 'vat_amount', 'line_total', 'total_with_vat'
        ]


class InvoiceListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'customer_name', 'date', 'bs_date',
            'due_date', 'total_amount', 'amount_paid', 'amount_due',
            'status', 'status_display', 'ird_synced', 'created_at'
        ]


class InvoiceDetailSerializer(serializers.ModelSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)
    customer_details = CustomerSerializer(source='customer', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    type_display = serializers.CharField(source='get_invoice_type_display', read_only=True)

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'fiscal_year', 'manual_reference',
            'invoice_type', 'type_display', 'status', 'status_display',
            'customer', 'customer_details',
            'billed_name', 'billed_address', 'billed_pan',
            'date', 'bs_date', 'due_date', 'bs_due_date',
            'sent_at', 'paid_at',
            'is_vat_applicable', 'vat_rate',
            'subtotal', 'discount_amount', 'discount_percent',
            'taxable_amount', 'vat_amount', 'exempt_amount', 'zero_rated_amount',
            'total_amount', 'amount_paid', 'amount_due',
            'ird_synced', 'ird_bill_id', 'ird_qr_data',
            'notes', 'terms', 'print_count',
            'lines', 'transaction',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'invoice_number', 'fiscal_year', 'subtotal', 'discount_amount',
            'taxable_amount', 'vat_amount', 'exempt_amount', 'zero_rated_amount',
            'total_amount', 'amount_due', 'ird_synced', 'ird_bill_id', 'ird_qr_data'
        ]


class InvoiceCreateSerializer(serializers.ModelSerializer):
    lines = InvoiceLineSerializer(many=True, write_only=True)

    class Meta:
        model = Invoice
        fields = [
            'customer', 'invoice_type', 'is_vat_applicable', 'vat_rate',
            'date', 'bs_date', 'due_date', 'bs_due_date',
            'manual_reference', 'discount_percent', 'discount_amount',
            'notes', 'terms', 'lines'
        ]

    def create(self, validated_data):
        lines_data = validated_data.pop('lines')
        tenant = self.context['request'].user.tenant

        # Snapshot customer details
        customer = validated_data['customer']
        validated_data['billed_name'] = customer.name
        validated_data['billed_address'] = customer.address
        validated_data['billed_pan'] = customer.pan_number

        invoice = Invoice.objects.create(tenant=tenant, **validated_data)

        for line_data in lines_data:
            item = line_data.get('item')
            if item:
                line_data['sku'] = item.code
                if not line_data.get('description'):
                    line_data['description'] = item.name
                line_data['unit_cost'] = item.get_unit_cost()

            InvoiceLine.objects.create(
                tenant=tenant,
                invoice=invoice,
                **line_data
            )

        invoice.calculate_totals()
        invoice.post_to_ledger()

        return invoice


class InvoicePaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoicePayment
        fields = [
            'id', 'invoice', 'date', 'bs_date', 'amount', 'method',
            'bank_account', 'reference_number', 'gateway_transaction_id',
            'notes', 'created_at'
        ]

    def validate_amount(self, value):
        invoice = self.context.get('invoice')
        if invoice and value > invoice.amount_due:
            raise serializers.ValidationError(
                f"Payment amount ({value}) exceeds amount due ({invoice.amount_due})"
            )
        return value


class CreditNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditNote
        fields = [
            'id', 'invoice', 'credit_number', 'date', 'bs_date',
            'subtotal', 'vat_amount', 'total_amount', 'reason',
            'reason_notes', 'status', 'ird_synced', 'created_at'
        ]
        read_only_fields = ['credit_number', 'ird_synced']