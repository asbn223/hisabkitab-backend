from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from .models import (
    TaxPeriod, VATReturn, VATTransaction, TDSSection,
    TDSDeduction, TDSReturn, TaxDeposit, TaxCertificate, TaxConfig
)
from .serializers import (
    TaxPeriodSerializer, VATReturnSerializer, VATTransactionSerializer,
    TDSSectionSerializer, TDSDeductionSerializer, TDSReturnSerializer,
    TaxDepositSerializer, TaxCertificateSerializer, TaxConfigSerializer
)
from .services import VATService, TDSService


class TaxConfigViewSet(viewsets.ModelViewSet):
    serializer_class = TaxConfigSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return TaxConfig.objects.filter(tenant=self.request.user.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant)


class TaxPeriodViewSet(viewsets.ModelViewSet):
    serializer_class = TaxPeriodSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status', 'period_type', 'fiscal_year']

    def get_queryset(self):
        return TaxPeriod.objects.filter(tenant=self.request.user.tenant)

    @action(detail=True, methods=['post'])
    def calculate(self, request, pk=None):
        """Calculate VAT for period."""
        period = self.get_object()
        result = VATService.calculate_period_vat(period)
        return Response(result)

    @action(detail=True, methods=['post'])
    def generate_return(self, request, pk=None):
        """Generate VAT return."""
        period = self.get_object()
        vat_return = VATService.generate_vat_return(period)
        serializer = VATReturnSerializer(vat_return)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """Tax dashboard."""
        tenant = request.user.tenant

        # Current period
        from datetime import datetime
        current_month = datetime.now().strftime('%Y-%m')
        current_period = TaxPeriod.objects.filter(
            tenant=tenant,
            year_month=current_month
        ).first()

        # Pending filings
        pending_vat = TaxPeriod.objects.filter(
            tenant=tenant,
            status='open',
            due_date__lt=timezone.now().date()
        ).count()

        # TDS to deposit
        pending_tds = TDSDeduction.objects.filter(
            tenant=tenant,
            is_deposited=False
        ).aggregate(total=Sum('tds_amount'))['total'] or 0

        # VAT position
        vat_position = Decimal('0')
        if current_period:
            vat_position = current_period.vat_payable

        return Response({
            'current_period': current_period.year_month if current_period else None,
            'vat_payable_current': vat_position,
            'pending_filings': pending_vat,
            'pending_tds_deposit': pending_tds,
            'is_vat_registered': getattr(tenant.tax_config, 'is_vat_registered', False)
        })


class VATReturnViewSet(viewsets.ModelViewSet):
    serializer_class = VATReturnSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return VATReturn.objects.filter(tenant=self.request.user.tenant)

    @action(detail=True, methods=['post'])
    def finalize(self, request, pk=None):
        """Finalize VAT return."""
        vat_return = self.get_object()
        vat_return.is_finalized = True
        vat_return.finalized_at = timezone.now()
        vat_return.save()
        return Response({'status': 'finalized'})

    @action(detail=True, methods=['post'])
    def submit_ird(self, request, pk=None):
        """Submit to IRD."""
        vat_return = self.get_object()
        result = VATService.submit_to_ird(vat_return)

        if result['success']:
            return Response(result)
        return Response(result, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def report(self, request, pk=None):
        """Detailed VAT report."""
        vat_return = self.get_object()

        # Get transactions
        transactions = VATTransaction.objects.filter(
            tenant=vat_return.tenant,
            tax_period=vat_return.tax_period
        ).order_by('source_date')

        return Response({
            'vat_return': VATReturnSerializer(vat_return).data,
            'transactions': VATTransactionSerializer(transactions, many=True).data,
            'summary': {
                'total_sales': vat_return.local_taxable_sales + vat_return.local_exempt_sales,
                'total_purchases': vat_return.local_taxable_purchases,
                'net_vat': vat_return.net_vat_payable
            }
        })


class VATTransactionViewSet(viewsets.ModelViewSet):
    serializer_class = VATTransactionSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['transaction_type', 'vat_type', 'tax_period']

    def get_queryset(self):
        return VATTransaction.objects.filter(tenant=self.request.user.tenant)


class TDSSectionViewSet(viewsets.ModelViewSet):
    serializer_class = TDSSectionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return TDSSection.objects.filter(tenant=self.request.user.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant)


class TDSDeductionViewSet(viewsets.ModelViewSet):
    serializer_class = TDSDeductionSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['tds_section', 'is_deposited', 'date']

    def get_queryset(self):
        return TDSDeduction.objects.filter(tenant=self.request.user.tenant)

    @action(detail=True, methods=['post'])
    def mark_deposited(self, request, pk=None):
        """Mark TDS as deposited to IRD."""
        deduction = self.get_object()
        deduction.is_deposited = True
        deduction.deposited_date = request.data.get('date')
        deduction.deposit_voucher_no = request.data.get('voucher_no', '')
        deduction.save()
        return Response({'status': 'marked_deposited'})

    @action(detail=False, methods=['get'])
    def pending(self, request):
        """Get pending TDS deductions."""
        deductions = self.get_queryset().filter(is_deposited=False)
        serializer = self.get_serializer(deductions, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def calculate(self, request):
        """Calculate TDS without saving."""
        section = request.data.get('section_code')
        amount = Decimal(request.data.get('amount', 0))
        tds = TDSService.calculate_tds(section, amount)
        return Response({
            'section': section,
            'amount': amount,
            'tds_rate': TDSService.RATES.get(section, 0),
            'tds_amount': tds,
            'net_amount': amount - tds
        })


class TDSReturnViewSet(viewsets.ModelViewSet):
    serializer_class = TDSReturnSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return TDSReturn.objects.filter(tenant=self.request.user.tenant)

    @action(detail=True, methods=['post'])
    def generate(self, request, pk=None):
        """Generate TDS return from deductions."""
        tds_return = self.get_object()

        deductions = TDSDeduction.objects.filter(
            tenant=tds_return.tenant,
            tax_period=tds_return.tax_period,
            tds_return__isnull=True
        )

        total = sum(d.tds_amount for d in deductions)
        tds_return.total_deducted = total
        tds_return.total_payable = total
        tds_return.save()

        # Link deductions
        deductions.update(tds_return=tds_return)

        return Response({
            'total_deducted': total,
            'deductions_count': deductions.count()
        })


class TaxDepositViewSet(viewsets.ModelViewSet):
    serializer_class = TaxDepositSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return TaxDeposit.objects.filter(tenant=self.request.user.tenant)

    def perform_create(self, serializer):
        deposit = serializer.save(tenant=self.request.user.tenant)
        # Create accounting entry
        self._create_accounting_entry(deposit)

    def _create_accounting_entry(self, deposit):
        """Create accounting entry for tax deposit."""
        from apps.accounts.models import Transaction, LedgerEntry

        # Determine payable account based on tax type
        if deposit.tax_type == 'vat':
            payable_account = Account.objects.get(tenant=deposit.tenant, code='2200')
        else:
            payable_account = Account.objects.get(tenant=deposit.tenant, code='2210')

        bank_account = Account.objects.get(tenant=deposit.tenant, code='1000')

        tx = Transaction.objects.create(
            tenant=deposit.tenant,
            reference_number=deposit.deposit_number,
            date=deposit.date,
            narration=f"Tax deposit - {deposit.get_tax_type_display()}",
            status='posted',
            source_type='tax_deposit',
            source_id=deposit.id
        )

        # Debit Tax Payable (reduce liability)
        LedgerEntry.objects.create(
            tenant=deposit.tenant,
            transaction=tx,
            account=payable_account,
            debit=deposit.total_amount,
            credit=Decimal('0')
        )

        # Credit Bank
        LedgerEntry.objects.create(
            tenant=deposit.tenant,
            transaction=tx,
            account=bank_account,
            debit=Decimal('0'),
            credit=deposit.total_amount
        )

        deposit.transaction = tx
        deposit.save()


class TaxCertificateViewSet(viewsets.ModelViewSet):
    serializer_class = TaxCertificateSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return TaxCertificate.objects.filter(tenant=self.request.user.tenant)

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Generate TDS certificate PDF."""
        certificate = self.get_object()
        # Generate PDF logic here
        return Response({
            'certificate_number': certificate.certificate_number,
            'download_url': f"/api/tax/certificates/{certificate.id}/pdf/"
        })