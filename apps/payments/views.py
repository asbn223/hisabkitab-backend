from django.utils import timezone
from rest_framework import viewsets, status, filters
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum

from .models import PaymentGateway, PaymentTransaction, BankAccount, BankStatement, BankStatementLine, PaymentRefund
from .serializers import (
    PaymentGatewaySerializer, PaymentTransactionSerializer,
    BankAccountSerializer, BankStatementSerializer, BankStatementLineSerializer
)
from .services import PaymentService, ReconciliationService


class PaymentGatewayViewSet(viewsets.ModelViewSet):
    serializer_class = PaymentGatewaySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return PaymentGateway.objects.filter(tenant=self.request.user.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant)


class PaymentTransactionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'payment_method', 'direction', 'is_reconciled']
    search_fields = ['transaction_id', 'customer_name', 'gateway_transaction_id']
    ordering_fields = ['initiated_at', 'amount', 'completed_at']

    def get_queryset(self):
        return PaymentTransaction.objects.filter(tenant=self.request.user.tenant)

    def get_serializer_class(self):
        return PaymentTransactionSerializer

    @action(detail=False, methods=['post'])
    def initialize(self, request):
        """Initialize a new payment."""
        gateway_type = request.data.get('gateway_type')
        amount = request.data.get('amount')

        result = PaymentService.initialize_payment(
            tenant=request.user.tenant,
            gateway_type=gateway_type,
            amount=amount,
            customer_name=request.data.get('customer_name', ''),
            customer_email=request.data.get('customer_email', ''),
            customer_phone=request.data.get('customer_phone', ''),
            source_type=request.data.get('source_type', ''),
            source_id=request.data.get('source_id'),
            source_number=request.data.get('source_number'),
            description=request.data.get('description', ''),
            success_url=request.data.get('success_url'),
            failure_url=request.data.get('failure_url'),
            user=request.user.username
        )

        if result.get('success'):
            return Response(result)
        return Response(result, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def refund(self, request, pk=None):
        """Process refund."""
        txn = self.get_object()
        amount = request.data.get('amount', txn.amount)

        # Gateway-specific refund
        gateway_class = PaymentService.GATEWAY_MAP.get(txn.payment_method)
        if gateway_class:
            gateway = gateway_class(txn.gateway)
            result = gateway.refund(txn, amount)

            if result.get('success'):
                # Create refund record
                PaymentRefund.objects.create(
                    tenant=request.user.tenant,
                    original_transaction=txn,
                    refund_id=f"REF-{txn.transaction_id}",
                    amount=amount,
                    reason=request.data.get('reason', ''),
                    status='completed',
                    processed_at=timezone.now()
                )
                txn.status = 'refunded' if amount >= txn.amount else 'partial_refund'
                txn.save()

            return Response(result)

        return Response({'error': 'Refund not supported'}, status=400)

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """Payment dashboard stats."""
        tenant = request.user.tenant

        today = timezone.now().date()

        # Today's transactions
        today_stats = PaymentTransaction.objects.filter(
            tenant=tenant,
            initiated_at__date=today,
            status='completed'
        ).aggregate(
            count=Sum('id'),
            amount=Sum('amount'),
            fees=Sum('gateway_fee')
        )

        # Monthly
        month_start = today.replace(day=1)
        monthly = PaymentTransaction.objects.filter(
            tenant=tenant,
            initiated_at__date__gte=month_start,
            status='completed'
        ).aggregate(total=Sum('amount'))

        # Pending reconciliation
        unreconciled = PaymentTransaction.objects.filter(
            tenant=tenant,
            status='completed',
            is_reconciled=False
        ).count()

        # By gateway
        by_gateway = PaymentTransaction.objects.filter(
            tenant=tenant,
            status='completed',
            initiated_at__date__gte=month_start
        ).values('payment_method').annotate(
            total=Sum('amount'),
            count=Sum('id')
        )

        return Response({
            'today_count': today_stats['count'] or 0,
            'today_amount': today_stats['amount'] or 0,
            'today_fees': today_stats['fees'] or 0,
            'monthly_total': monthly['total'] or 0,
            'unreconciled_count': unreconciled,
            'by_gateway': list(by_gateway)
        })


class BankAccountViewSet(viewsets.ModelViewSet):
    serializer_class = BankAccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return BankAccount.objects.filter(tenant=self.request.user.tenant)

    def perform_create(self, serializer):
        # Auto-create ledger account
        if not serializer.validated_data.get('ledger_account'):
            from apps.accounts.models import Account
            account = Account.objects.create(
                tenant=self.request.user.tenant,
                code=f"1010{BankAccount.objects.filter(tenant=self.request.user.tenant).count() + 1}",
                name=f"Bank - {serializer.validated_data['bank_name']}",
                type='asset',
                is_system=True
            )
            serializer.save(tenant=self.request.user.tenant, ledger_account=account)
        else:
            serializer.save(tenant=self.request.user.tenant)


class BankStatementViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return BankStatement.objects.filter(tenant=self.request.user.tenant)

    def get_serializer_class(self):
        return BankStatementSerializer

    @action(detail=True, methods=['post'])
    def import_file(self, request, pk=None):
        """Import statement file."""
        statement = self.get_object()
        file = request.FILES.get('file')
        file_format = request.data.get('format', 'csv')

        if not file:
            return Response({'error': 'No file provided'}, status=400)

        result = ReconciliationService.import_statement(
            bank_account=statement.account,
            file_data=file.read(),
            file_format=file_format
        )

        return Response({
            'success': True,
            'statement_id': result.id,
            'lines_imported': result.lines.count()
        })

    @action(detail=True, methods=['get'])
    def unreconciled(self, request, pk=None):
        """Get unreconciled lines."""
        statement = self.get_object()
        lines = statement.lines.filter(status='unreconciled')
        serializer = BankStatementLineSerializer(lines, many=True)
        return Response(serializer.data)


class BankStatementLineViewSet(viewsets.ModelViewSet):
    serializer_class = BankStatementLineSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['status', 'date']

    def get_queryset(self):
        return BankStatementLine.objects.filter(
            account__tenant=self.request.user.tenant
        )

    @action(detail=True, methods=['post'])
    def match(self, request, pk=None):
        """Manually match line to transaction."""
        line = self.get_object()
        transaction_id = request.data.get('transaction_id')

        if transaction_id:
            transaction = PaymentTransaction.objects.get(id=transaction_id)
            ReconciliationService.match_line(line, transaction=transaction)
        else:
            # Match to invoice or bill
            invoice_id = request.data.get('invoice_id')
            bill_id = request.data.get('bill_id')

            invoice = None
            bill = None

            if invoice_id:
                from apps.invoicing.models import Invoice
                invoice = Invoice.objects.get(id=invoice_id)
            if bill_id:
                from apps.purchases.models import SupplierBill
                bill = SupplierBill.objects.get(id=bill_id)

            ReconciliationService.match_line(line, invoice=invoice, bill=bill)

        return Response({'status': 'matched'})

    @action(detail=True, methods=['post'])
    def auto_match(self, request, pk=None):
        """Run auto-match on single line."""
        line = self.get_object()
        suggestions = ReconciliationService.auto_match(line)
        return Response({'suggestions': suggestions})


# Callback views (public, no auth required)
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponseRedirect


@csrf_exempt
def esewa_callback(request, status):
    """Handle eSewa callback."""
    if request.method == 'POST':
        data = request.POST.dict()
    else:
        data = request.GET.dict()

    result = PaymentService.process_callback('esewa', data, request.GET)

    if result.get('success'):
        return HttpResponseRedirect(result['redirect_url'])
    return HttpResponseRedirect(result['redirect_url'])


@csrf_exempt
def khalti_callback(request, status):
    """Handle Khalti callback."""
    if request.method == 'POST':
        import json
        data = json.loads(request.body)
    else:
        data = request.GET.dict()

    result = PaymentService.process_callback('khalti', data, request.GET)

    if result.get('success'):
        return HttpResponseRedirect(result['redirect_url'])
    return HttpResponseRedirect(result['redirect_url'])