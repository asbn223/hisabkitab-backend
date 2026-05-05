from rest_framework import serializers
from .models import (
    Supplier, PurchaseRequisition, PurchaseRequisitionLine,
    PurchaseOrder, PurchaseOrderLine, GoodsReceiptNote, GRNLine,
    SupplierBill, SupplierBillLine, SupplierPayment
)
from apps.inventory.serializers import InventoryItemSerializer


class SupplierSerializer(serializers.ModelSerializer):
    balance = serializers.DecimalField(
        max_digits=15,
        decimal_places=4,
        source='get_balance',
        read_only=True
    )

    class Meta:
        model = Supplier
        fields = [
            'id', 'code', 'name', 'name_nepali', 'legal_name',
            'pan_number', 'vat_registered', 'supplier_type',
            'address', 'phone', 'email', 'contact_person',
            'credit_days', 'credit_limit', 'payable_account',
            'is_active', 'is_approved', 'bank_name', 'bank_account',
            'balance', 'created_at'
        ]


class PurchaseRequisitionLineSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)

    class Meta:
        model = PurchaseRequisitionLine
        fields = [
            'id', 'item', 'item_name', 'description', 'quantity',
            'unit', 'estimated_price', 'total', 'ordered_quantity'
        ]
        read_only_fields = ['total']


class PurchaseRequisitionSerializer(serializers.ModelSerializer):
    lines = PurchaseRequisitionLineSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = PurchaseRequisition
        fields = [
            'id', 'requisition_number', 'date', 'bs_date',
            'department', 'requested_by', 'status', 'status_display',
            'total_amount', 'approved_by', 'approved_at', 'notes',
            'lines', 'created_at'
        ]
        read_only_fields = ['requisition_number', 'total_amount']


class PurchaseRequisitionCreateSerializer(serializers.ModelSerializer):
    lines = PurchaseRequisitionLineSerializer(many=True, write_only=True)

    class Meta:
        model = PurchaseRequisition
        fields = [
            'date', 'bs_date', 'department', 'requested_by',
            'notes', 'lines'
        ]

    def create(self, validated_data):
        lines_data = validated_data.pop('lines')
        tenant = self.context['request'].user.tenant

        req = PurchaseRequisition.objects.create(
            tenant=tenant,
            **validated_data
        )

        total = Decimal('0')
        for line_data in lines_data:
            line = PurchaseRequisitionLine.objects.create(
                requisition=req,
                **line_data
            )
            total += line.total

        req.total_amount = total
        req.save()

        return req


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    pending_quantity = serializers.DecimalField(
        max_digits=15,
        decimal_places=4,
        read_only=True
    )

    class Meta:
        model = PurchaseOrderLine
        fields = [
            'id', 'item', 'item_name', 'description', 'specification',
            'quantity', 'unit', 'unit_price', 'discount_percent',
            'line_discount', 'line_total', 'vat_type',
            'received_quantity', 'billed_quantity', 'pending_quantity',
            'expense_account'
        ]
        read_only_fields = ['line_discount', 'line_total']


class PurchaseOrderListSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            'id', 'po_number', 'supplier_name', 'date', 'bs_date',
            'delivery_date', 'status', 'status_display',
            'total_amount', 'received_amount', 'billed_amount',
            'created_at'
        ]


class PurchaseOrderDetailSerializer(serializers.ModelSerializer):
    lines = PurchaseOrderLineSerializer(many=True, read_only=True)
    supplier_details = SupplierSerializer(source='supplier', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    type_display = serializers.CharField(source='get_order_type_display', read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            'id', 'po_number', 'fiscal_year', 'order_type', 'type_display',
            'status', 'status_display', 'supplier', 'supplier_details',
            'supplier_ref', 'date', 'bs_date', 'delivery_date', 'bs_delivery_date',
            'delivery_location', 'delivery_terms', 'currency', 'exchange_rate',
            'is_vat_applicable', 'vat_rate', 'subtotal', 'discount_amount',
            'vat_amount', 'shipping_cost', 'total_amount', 'received_amount',
            'billed_amount', 'requisition', 'payment_terms', 'notes',
            'lines', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'po_number', 'fiscal_year', 'subtotal', 'vat_amount', 'total_amount'
        ]


class PurchaseOrderCreateSerializer(serializers.ModelSerializer):
    lines = PurchaseOrderLineSerializer(many=True, write_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            'supplier', 'order_type', 'date', 'bs_date',
            'delivery_date', 'bs_delivery_date', 'delivery_location',
            'supplier_ref', 'is_vat_applicable', 'vat_rate',
            'discount_amount', 'shipping_cost', 'payment_terms',
            'notes', 'requisition', 'lines'
        ]

    def create(self, validated_data):
        lines_data = validated_data.pop('lines')
        tenant = self.context['request'].user.tenant

        po = PurchaseOrder.objects.create(
            tenant=tenant,
            created_by=self.context['request'].user.username,
            **validated_data
        )

        for line_data in lines_data:
            item = line_data.get('item')
            if item:
                line_data['description'] = line_data.get('description', item.name)

            PurchaseOrderLine.objects.create(po=po, **line_data)

        po.calculate_totals()

        # Update requisition status if linked
        if po.requisition:
            po.requisition.status = 'ordered'
            po.requisition.save()

        return po


class GRNLineSerializer(serializers.ModelSerializer):
    po_line_details = serializers.SerializerMethodField()

    class Meta:
        model = GRNLine
        fields = [
            'id', 'po_line', 'po_line_details', 'ordered_quantity',
            'received_quantity', 'accepted_quantity', 'rejected_quantity',
            'unit_cost', 'total_cost', 'batch_number', 'expiry_date',
            'quality_status'
        ]

    def get_po_line_details(self, obj):
        return {
            'description': obj.po_line.description,
            'item_name': obj.po_line.item.name if obj.po_line.item else None,
            'sku': obj.po_line.item.code if obj.po_line.item else None
        }


class GRNListSerializer(serializers.ModelSerializer):
    po_number = serializers.CharField(source='po.po_number', read_only=True)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = GoodsReceiptNote
        fields = [
            'id', 'grn_number', 'po_number', 'supplier_name',
            'date', 'bs_date', 'status', 'status_display',
            'total_quantity', 'total_amount', 'created_at'
        ]


class GRNDetailSerializer(serializers.ModelSerializer):
    lines = GRNLineSerializer(many=True, read_only=True)
    po_details = PurchaseOrderListSerializer(source='po', read_only=True)

    class Meta:
        model = GoodsReceiptNote
        fields = [
            'id', 'grn_number', 'fiscal_year', 'po', 'po_details',
            'supplier', 'supplier_delivery_note', 'date', 'bs_date',
            'status', 'total_quantity', 'total_amount',
            'inspected_by', 'inspection_notes', 'lines',
            'created_at'
        ]
        read_only_fields = ['grn_number', 'fiscal_year', 'total_quantity', 'total_amount']


class GRNCreateSerializer(serializers.ModelSerializer):
    lines = GRNLineSerializer(many=True, write_only=True)

    class Meta:
        model = GoodsReceiptNote
        fields = ['po', 'supplier_delivery_note', 'date', 'bs_date', 'lines', 'inspection_notes']

    def validate(self, data):
        # Validate lines belong to PO
        po = data['po']
        po_line_ids = [l['po_line'].id for l in data['lines']]
        valid_ids = list(po.lines.values_list('id', flat=True))

        invalid = set(po_line_ids) - set(valid_ids)
        if invalid:
            raise serializers.ValidationError(f"Invalid PO lines: {invalid}")

        return data

    def create(self, validated_data):
        lines_data = validated_data.pop('lines')
        tenant = self.context['request'].user.tenant

        grn = GoodsReceiptNote.objects.create(
            tenant=tenant,
            supplier=validated_data['po'].supplier,
            created_by=self.context['request'].user.username,
            **validated_data
        )

        total_qty = Decimal('0')
        total_amt = Decimal('0')

        for line_data in lines_data:
            po_line = line_data['po_line']
            line_data['ordered_quantity'] = po_line.quantity
            line_data['unit_cost'] = po_line.unit_price  # Or actual cost if different

            line = GRNLine.objects.create(grn=grn, **line_data)
            total_qty += line.received_quantity
            total_amt += line.total_cost

        grn.total_quantity = total_qty
        grn.total_amount = total_amt
        grn.save()

        return grn


class SupplierBillLineSerializer(serializers.ModelSerializer):
    grn_line_details = serializers.SerializerMethodField()

    class Meta:
        model = SupplierBillLine
        fields = [
            'id', 'grn_line', 'grn_line_details', 'description',
            'quantity', 'unit', 'unit_price', 'line_total',
            'vat_type', 'expense_account'
        ]
        read_only_fields = ['line_total']

    def get_grn_line_details(self, obj):
        if obj.grn_line:
            return {
                'grn_number': obj.grn_line.grn.grn_number,
                'received_quantity': obj.grn_line.received_quantity,
                'batch_number': obj.grn_line.batch_number
            }
        return None


class SupplierBillListSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = SupplierBill
        fields = [
            'id', 'bill_number', 'supplier_name', 'supplier_bill_number',
            'date', 'bs_date', 'due_date', 'status', 'status_display',
            'total_amount', 'amount_paid', 'amount_due', 'created_at'
        ]


class SupplierBillDetailSerializer(serializers.ModelSerializer):
    lines = SupplierBillLineSerializer(many=True, read_only=True)
    supplier_details = SupplierSerializer(source='supplier', read_only=True)
    po_number = serializers.CharField(source='po.po_number', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = SupplierBill
        fields = [
            'id', 'bill_number', 'fiscal_year', 'supplier', 'supplier_details',
            'supplier_bill_number', 'supplier_bill_date', 'po', 'po_number',
            'grns', 'date', 'bs_date', 'due_date', 'bs_due_date',
            'bill_type', 'status', 'status_display', 'is_vat_applicable',
            'vat_rate', 'subtotal', 'discount_amount', 'vat_amount',
            'total_amount', 'amount_paid', 'amount_due',
            'tds_applicable', 'tds_rate', 'tds_amount',
            'lines', 'notes', 'created_at'
        ]
        read_only_fields = [
            'bill_number', 'fiscal_year', 'subtotal', 'vat_amount',
            'total_amount', 'amount_due'
        ]


class SupplierBillCreateSerializer(serializers.ModelSerializer):
    lines = SupplierBillLineSerializer(many=True, write_only=True)
    grn_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )

    class Meta:
        model = SupplierBill
        fields = [
            'supplier', 'supplier_bill_number', 'supplier_bill_date',
            'po', 'grn_ids', 'date', 'bs_date', 'due_date', 'bs_due_date',
            'bill_type', 'is_vat_applicable', 'vat_rate',
            'discount_amount', 'tds_applicable', 'tds_rate',
            'notes', 'lines'
        ]

    def create(self, validated_data):
        lines_data = validated_data.pop('lines')
        grn_ids = validated_data.pop('grn_ids', [])
        tenant = self.context['request'].user.tenant

        bill = SupplierBill.objects.create(
            tenant=tenant,
            created_by=self.context['request'].user.username,
            **validated_data
        )

        # Link GRNs
        if grn_ids:
            bill.grns.set(GoodsReceiptNote.objects.filter(id__in=grn_ids))

        for line_data in lines_data:
            SupplierBillLine.objects.create(bill=bill, **line_data)

        bill.calculate_totals()

        return bill


class SupplierPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierPayment
        fields = [
            'id', 'supplier', 'bill', 'date', 'bs_date', 'amount',
            'method', 'bank_account', 'reference_number', 'notes',
            'created_at'
        ]

    def validate_amount(self, value):
        bill = self.context.get('bill')
        if bill and value > bill.amount_due:
            raise serializers.ValidationError(
                f"Payment {value} exceeds amount due {bill.amount_due}"
            )
        return value