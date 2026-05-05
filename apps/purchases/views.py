from datetime import timedelta
from decimal import Decimal

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum, Q
from django.utils import timezone

from .models import (
    Supplier, PurchaseRequisition, PurchaseOrder, GoodsReceiptNote,
    SupplierBill, SupplierPayment
)
from .serializers import (
    SupplierSerializer, PurchaseRequisitionSerializer, PurchaseRequisitionCreateSerializer,
    PurchaseOrderListSerializer, PurchaseOrderDetailSerializer, PurchaseOrderCreateSerializer,
    GRNListSerializer, GRNDetailSerializer, GRNCreateSerializer,
    SupplierBillListSerializer, SupplierBillDetailSerializer, SupplierBillCreateSerializer,
    SupplierPaymentSerializer
)


class SupplierViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['supplier_type', 'is_active', 'vat_registered']
    search_fields = ['name', 'code', 'pan_number']

    def get_queryset(self):
        return Supplier.objects.filter(tenant=self.request.user.tenant)

    def perform_create(self, serializer):
        # Auto-create payable account
        if not serializer.validated_data.get('payable_account'):
            from apps.accounts.models import Account
            payable, _ = Account.objects.get_or_create(
                tenant=self.request.user.tenant,
                code='2100',
                defaults={
                    'name': 'Accounts Payable',
                    'type': 'liability',
                    'is_system': True
                }
            )
            serializer.save(
                tenant=self.request.user.tenant,
                payable_account=payable
            )
        else:
            serializer.save(tenant=self.request.user.tenant)

    @action(detail=True, methods=['get'])
    def statement(self, request, pk=None):
        """Get supplier statement of account."""
        supplier = self.get_object()
        bills = SupplierBill.objects.filter(
            supplier=supplier,
            tenant=request.user.tenant
        ).order_by('date')

        statement = []
        balance = Decimal('0')

        for bill in bills:
            balance += bill.total_amount
            payments = bill.payments.all()
            for payment in payments:
                balance -= payment.amount

            statement.append({
                'date': bill.date,
                'reference': bill.bill_number,
                'description': f"Bill {bill.supplier_bill_number or ''}",
                'debit': float(bill.total_amount),
                'credit': float(sum(p.amount for p in payments)),
                'balance': float(balance)
            })

        return Response({
            'supplier': supplier.name,
            'opening_balance': 0,
            'transactions': statement,
            'closing_balance': float(balance)
        })


class PurchaseRequisitionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['status', 'department']
    search_fields = ['requisition_number', 'requested_by']

    def get_queryset(self):
        return PurchaseRequisition.objects.filter(tenant=self.request.user.tenant)

    def get_serializer_class(self):
        if self.action in ['create', 'update']:
            return PurchaseRequisitionCreateSerializer
        return PurchaseRequisitionSerializer

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve requisition."""
        req = self.get_object()
        req.status = 'approved'
        req.approved_by = request.user.username
        req.approved_at = timezone.now()
        req.save()
        return Response({'status': 'approved'})

    @action(detail=True, methods=['post'])
    def convert_to_po(self, request, pk=None):
        """Convert approved requisition to PO."""
        req = self.get_object()
        if req.status != 'approved':
            return Response(
                {'error': 'Requisition must be approved first'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Return template for PO creation with requisition data
        return Response({
            'requisition_id': req.id,
            'lines': [
                {
                    'item_id': line.item.id,
                    'description': line.description,
                    'quantity': line.quantity - line.ordered_quantity,
                    'unit': line.unit,
                    'estimated_price': line.estimated_price
                }
                for line in req.lines.all()
                if line.quantity > line.ordered_quantity
            ]
        })


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'order_type', 'supplier']
    search_fields = ['po_number', 'supplier__name', 'supplier_ref']
    ordering_fields = ['date', 'delivery_date', 'total_amount']

    def get_queryset(self):
        return PurchaseOrder.objects.filter(tenant=self.request.user.tenant)

    def get_serializer_class(self):
        if self.action == 'list':
            return PurchaseOrderListSerializer
        elif self.action in ['create', 'update']:
            return PurchaseOrderCreateSerializer
        return PurchaseOrderDetailSerializer

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        """Mark PO as sent to supplier."""
        po = self.get_object()
        po.status = 'sent'
        po.save()
        return Response({'status': 'sent'})

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """Close PO manually."""
        po = self.get_object()
        po.status = 'closed'
        po.save()
        return Response({'status': 'closed'})

    @action(detail=False, methods=['get'])
    def pending_receipt(self, request):
        """Get POs with pending receipts."""
        pos = PurchaseOrder.objects.filter(
            tenant=request.user.tenant,
            status__in=['sent', 'partial']
        )
        serializer = PurchaseOrderListSerializer(pos, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """Purchase dashboard."""
        tenant = request.user.tenant

        # PO stats
        total_pos = PurchaseOrder.objects.filter(tenant=tenant).count()
        pending_pos = PurchaseOrder.objects.filter(
            tenant=tenant,
            status__in=['draft', 'sent', 'partial']
        ).count()

        # Amounts
        total_ordered = PurchaseOrder.objects.filter(
            tenant=tenant
        ).aggregate(total=Sum('total_amount'))['total'] or 0

        total_received = PurchaseOrder.objects.filter(
            tenant=tenant
        ).aggregate(total=Sum('received_amount'))['total'] or 0

        # Overdue deliveries
        today = timezone.now().date()
        overdue = PurchaseOrder.objects.filter(
            tenant=tenant,
            delivery_date__lt=today,
            status__in=['sent', 'partial']
        ).count()

        return Response({
            'total_pos': total_pos,
            'pending_pos': pending_pos,
            'total_ordered': total_ordered,
            'total_received': total_received,
            'overdue_deliveries': overdue
        })


class GoodsReceiptNoteViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['status', 'po', 'supplier']
    search_fields = ['grn_number', 'supplier_delivery_note']

    def get_queryset(self):
        return GoodsReceiptNote.objects.filter(tenant=self.request.user.tenant)

    def get_serializer_class(self):
        if self.action == 'list':
            return GRNListSerializer
        elif self.action in ['create', 'update']:
            return GRNCreateSerializer
        return GRNDetailSerializer

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Confirm GRN and update inventory."""
        grn = self.get_object()
        success = grn.confirm_receipt()

        if success:
            return Response({
                'status': 'confirmed',
                'message': 'Goods receipt confirmed and inventory updated'
            })
        return Response(
            {'error': 'GRN already confirmed or invalid status'},
            status=status.HTTP_400_BAD_REQUEST
        )

    @action(detail=False, methods=['get'])
    def pending_billing(self, request):
        """Get confirmed GRNs not yet billed."""
        grns = GoodsReceiptNote.objects.filter(
            tenant=request.user.tenant,
            status='confirmed'
        )
        serializer = GRNListSerializer(grns, many=True)
        return Response(serializer.data)


class SupplierBillViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'bill_type', 'supplier']
    search_fields = ['bill_number', 'supplier_bill_number', 'supplier__name']
    ordering_fields = ['date', 'due_date', 'total_amount']

    def get_queryset(self):
        return SupplierBill.objects.filter(tenant=self.request.user.tenant)

    def get_serializer_class(self):
        if self.action == 'list':
            return SupplierBillListSerializer
        elif self.action in ['create', 'update']:
            return SupplierBillCreateSerializer
        return SupplierBillDetailSerializer

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Confirm bill and post to ledger."""
        bill = self.get_object()
        success = bill.confirm_bill()

        if success:
            return Response({
                'status': 'confirmed',
                'transaction_id': bill.transaction.id if bill.transaction else None
            })
        return Response(
            {'error': 'Bill already confirmed'},
            status=status.HTTP_400_BAD_REQUEST
        )

    @action(detail=False, methods=['get'])
    def aging(self, request):
        """Payables aging report."""
        tenant = request.user.tenant
        today = timezone.now().date()

        buckets = {
            'current': (0, 0),
            '1_30': (1, 30),
            '31_60': (31, 60),
            '61_90': (61, 90),
            '90_plus': (91, 9999)
        }

        report = {}
        for name, (start, end) in buckets.items():
            end_date = today - timedelta(days=start)
            start_date = today - timedelta(days=end) if end > 0 else None

            query = SupplierBill.objects.filter(
                tenant=tenant,
                status__in=['confirmed', 'partial'],
                due_date__lte=end_date
            )
            if start_date:
                query = query.filter(due_date__gt=start_date)

            agg = query.aggregate(
                amount=Sum('amount_due'),
                count=Sum('id')
            )
            report[name] = {
                'amount': agg['amount'] or 0,
                'count': agg['count'] or 0
            }

        return Response(report)

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """Bills dashboard."""
        tenant = request.user.tenant

        total_payable = SupplierBill.objects.filter(
            tenant=tenant,
            status__in=['confirmed', 'partial']
        ).aggregate(total=Sum('amount_due'))['total'] or 0

        overdue = SupplierBill.objects.filter(
            tenant=tenant,
            status__in=['confirmed', 'partial'],
            due_date__lt=timezone.now().date()
        ).aggregate(total=Sum('amount_due'))['total'] or 0

        this_month = SupplierBill.objects.filter(
            tenant=tenant,
            date__month=timezone.now().month
        ).aggregate(total=Sum('total_amount'))['total'] or 0

        return Response({
            'total_payable': total_payable,
            'overdue_amount': overdue,
            'this_month_purchases': this_month
        })


class SupplierPaymentViewSet(viewsets.ModelViewSet):
    serializer_class = SupplierPaymentSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['method', 'date', 'supplier']

    def get_queryset(self):
        return SupplierPayment.objects.filter(tenant=self.request.user.tenant)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        bill_id = self.request.data.get('bill')
        if bill_id:
            context['bill'] = SupplierBill.objects.filter(id=bill_id).first()
        return context

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.user.tenant,
            created_by=self.request.user.username
        )