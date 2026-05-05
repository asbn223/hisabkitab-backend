from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import timedelta

from .models import Customer, Invoice, InvoiceLine, InvoicePayment, CreditNote
from .serializers import (
    CustomerSerializer, InvoiceListSerializer, InvoiceDetailSerializer,
    InvoiceCreateSerializer, InvoiceLineSerializer, InvoicePaymentSerializer,
    CreditNoteSerializer
)
from .services import IRDService, PDFService
from ..accounts.models import Account


class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['customer_type', 'is_active', 'vat_registered']
    search_fields = ['name', 'code', 'pan_number', 'email']

    def get_queryset(self):
        return Customer.objects.filter(tenant=self.request.user.tenant)

    def perform_create(self, serializer):
        # Auto-assign receivable account if not set
        if not serializer.validated_data.get('receivable_account'):
            ar_account, _ = Account.objects.get_or_create(
                tenant=self.request.user.tenant,
                code='1200',
                defaults={
                    'name': 'Accounts Receivable',
                    'type': 'asset',
                    'is_system': True
                }
            )
            serializer.save(
                tenant=self.request.user.tenant,
                receivable_account=ar_account
            )
        else:
            serializer.save(tenant=self.request.user.tenant)


class InvoiceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'invoice_type', 'customer', 'ird_synced']
    search_fields = ['invoice_number', 'customer__name', 'manual_reference']
    ordering_fields = ['date', 'due_date', 'total_amount', 'created_at']

    def get_queryset(self):
        return Invoice.objects.filter(
            tenant=self.request.user.tenant
        ).select_related('customer', 'transaction').prefetch_related('lines', 'payments')

    def get_serializer_class(self):
        if self.action == 'list':
            return InvoiceListSerializer
        elif self.action in ['create', 'update']:
            return InvoiceCreateSerializer
        return InvoiceDetailSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user.username)

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        """Mark invoice as sent."""
        invoice = self.get_object()
        invoice.status = 'sent'
        invoice.sent_at = timezone.now()
        invoice.save()

        # TODO: Send email notification

        return Response({'status': 'sent', 'message': 'Invoice marked as sent'})

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel invoice (only if not paid)."""
        invoice = self.get_object()

        if invoice.status in ['paid', 'partial']:
            return Response(
                {'error': 'Cannot cancel paid/partial invoice. Use credit note.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Reverse transaction if posted
        if invoice.transaction and invoice.transaction.status == 'posted':
            invoice.transaction.status = 'cancelled'
            invoice.transaction.cancelled_at = timezone.now()
            invoice.transaction.cancelled_by = request.user.username
            invoice.transaction.cancellation_reason = "Invoice cancelled"
            invoice.transaction.save()

        invoice.status = 'cancelled'
        invoice.save()

        return Response({'status': 'cancelled'})

    @action(detail=True, methods=['post'])
    def submit_ird(self, request, pk=None):
        """Submit invoice to IRD."""
        invoice = self.get_object()

        if invoice.ird_synced:
            return Response(
                {'error': 'Already synced with IRD'},
                status=status.HTTP_400_BAD_REQUEST
            )

        result = IRDService.submit_invoice(invoice)

        if result['success']:
            return Response({
                'status': 'synced',
                'ird_bill_id': invoice.ird_bill_id
            })
        else:
            return Response(
                {'error': result.get('error', 'IRD sync failed')},
                status=status.HTTP_502_BAD_GATEWAY
            )

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        """Generate PDF invoice."""
        invoice = self.get_object()
        pdf_content = PDFService.generate_invoice_pdf(invoice)

        response = Response(pdf_content, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{invoice.invoice_number}.pdf"'
        return response

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """Invoice dashboard stats."""
        tenant = request.user.tenant

        # Outstanding receivables
        outstanding = Invoice.objects.filter(
            tenant=tenant,
            status__in=['sent', 'partial', 'overdue']
        ).aggregate(
            total=Sum('amount_due'),
            count=Sum('id')
        )

        # Overdue
        today = timezone.now().date()
        overdue = Invoice.objects.filter(
            tenant=tenant,
            status='overdue'
        ).aggregate(total=Sum('amount_due'))

        # This month
        from datetime import datetime
        current_month = datetime.now().month
        monthly = Invoice.objects.filter(
            tenant=tenant,
            date__month=current_month,
            status__in=['sent', 'partial', 'paid']
        ).aggregate(total=Sum('total_amount'))

        # Recent invoices
        recent = Invoice.objects.filter(tenant=tenant).order_by('-created_at')[:5]

        return Response({
            'outstanding_amount': outstanding['total'] or 0,
            'outstanding_count': outstanding['count'] or 0,
            'overdue_amount': overdue['total'] or 0,
            'monthly_sales': monthly['total'] or 0,
            'recent_invoices': InvoiceListSerializer(recent, many=True).data
        })

    @action(detail=False, methods=['get'])
    def aging(self, request):
        """Accounts Receivable aging report."""
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

            query = Invoice.objects.filter(
                tenant=tenant,
                status__in=['sent', 'partial', 'overdue'],
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


class InvoicePaymentViewSet(viewsets.ModelViewSet):
    serializer_class = InvoicePaymentSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['method', 'date']

    def get_queryset(self):
        return InvoicePayment.objects.filter(tenant=self.request.user.tenant)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        invoice_id = self.request.data.get('invoice')
        if invoice_id:
            context['invoice'] = Invoice.objects.filter(id=invoice_id).first()
        return context

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.user.tenant,
            created_by=self.request.user.username
        )


class CreditNoteViewSet(viewsets.ModelViewSet):
    serializer_class = CreditNoteSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return CreditNote.objects.filter(tenant=self.request.user.tenant)