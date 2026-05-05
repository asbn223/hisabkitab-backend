import datetime
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.http import HttpResponse
from datetime import datetime

from .models import SavedReport, ReportExport
from .serializers import SavedReportSerializer, ReportExportSerializer
from .services import FinancialReportService, OperationalReportService
from .exporters import PDFExporter, ExcelExporter


class ReportViewSet(viewsets.ViewSet):
    """
    Main reports viewset - doesn't use standard CRUD.
    """
    permission_classes = [IsAuthenticated]

    def _get_tenant(self):
        return self.request.user.tenant

    def _parse_dates(self, request):
        """Parse date parameters from request."""
        start = request.query_params.get('start_date')
        end = request.query_params.get('end_date')
        period = request.query_params.get('period', 'current_month')

        if start and end:
            from datetime import datetime
            start_date = datetime.strptime(start, '%Y-%m-%d').date()
            end_date = datetime.strptime(end, '%Y-%m-%d').date()
        else:
            start_date, end_date = FinancialReportService.get_date_range(period)

        return start_date, end_date

    @action(detail=False, methods=['get'])
    def trial_balance(self, request):
        """Generate Trial Balance."""
        start_date, end_date = self._parse_dates(request)
        include_zero = request.query_params.get('include_zero', 'false').lower() == 'true'

        data = FinancialReportService.trial_balance(
            self._get_tenant(),
            start_date,
            end_date,
            include_zero
        )

        return Response(data)

    @action(detail=False, methods=['get'])
    def profit_loss(self, request):
        """Generate Profit & Loss."""
        start_date, end_date = self._parse_dates(request)
        compare = request.query_params.get('compare_previous', 'false').lower() == 'true'

        data = FinancialReportService.profit_loss(
            self._get_tenant(),
            start_date,
            end_date,
            compare
        )

        return Response(data)

    @action(detail=False, methods=['get'])
    def balance_sheet(self, request):
        """Generate Balance Sheet."""
        as_of = request.query_params.get('as_of_date')
        if as_of:
            from datetime import datetime
            as_of_date = datetime.strptime(as_of, '%Y-%m-%d').date()
        else:
            as_of_date = datetime.now().date()

        data = FinancialReportService.balance_sheet(
            self._get_tenant(),
            as_of_date
        )

        return Response(data)

    @action(detail=False, methods=['get'])
    def cash_flow(self, request):
        """Generate Cash Flow Statement."""
        start_date, end_date = self._parse_dates(request)

        data = FinancialReportService.cash_flow(
            self._get_tenant(),
            start_date,
            end_date
        )

        return Response(data)

    @action(detail=False, methods=['get'])
    def general_ledger(self, request):
        """Generate General Ledger."""
        account_code = request.query_params.get('account_code')
        if not account_code:
            return Response({'error': 'account_code required'}, status=400)

        start_date, end_date = self._parse_dates(request)

        data = FinancialReportService.general_ledger(
            self._get_tenant(),
            account_code,
            start_date,
            end_date
        )

        return Response(data)

    @action(detail=False, methods=['get'])
    def receivables(self, request):
        """Receivables Aging."""
        as_of = request.query_params.get('as_of_date')
        if as_of:
            from datetime import datetime
            as_of_date = datetime.strptime(as_of, '%Y-%m-%d').date()
        else:
            as_of_date = None

        data = OperationalReportService.receivables_aging(
            self._get_tenant(),
            as_of_date
        )

        return Response(data)

    @action(detail=False, methods=['get'])
    def payables(self, request):
        """Payables Aging."""
        as_of = request.query_params.get('as_of_date')
        if as_of:
            from datetime import datetime
            as_of_date = datetime.strptime(as_of, '%Y-%m-%d').date()
        else:
            as_of_date = None

        data = OperationalReportService.payables_aging(
            self._get_tenant(),
            as_of_date
        )

        return Response(data)

    @action(detail=False, methods=['get'])
    def sales(self, request):
        """Sales Report."""
        start_date, end_date = self._parse_dates(request)
        group_by = request.query_params.get('group_by', 'day')

        data = OperationalReportService.sales_report(
            self._get_tenant(),
            start_date,
            end_date,
            group_by
        )

        return Response(data)

    @action(detail=False, methods=['get'])
    def inventory(self, request):
        """Inventory Report."""
        as_of = request.query_params.get('as_of_date')
        if as_of:
            from datetime import datetime
            as_of_date = datetime.strptime(as_of, '%Y-%m-%d').date()
        else:
            as_of_date = None

        data = OperationalReportService.inventory_report(
            self._get_tenant(),
            as_of_date
        )

        return Response(data)

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """Executive Dashboard KPIs."""
        tenant = self._get_tenant()
        today = datetime.now().date()
        month_start = today.replace(day=1)

        # Key metrics
        from apps.invoicing.models import Invoice
        from apps.purchases.models import SupplierBill
        from apps.accounts.models import Account

        # Monthly sales
        monthly_sales = Invoice.objects.filter(
            tenant=tenant,
            invoice_date__gte=month_start,
            status__in=['sent', 'partial', 'paid']
        ).aggregate(total=Sum('total_amount'))['total'] or 0

        # Outstanding receivables
        receivables = Invoice.objects.filter(
            tenant=tenant,
            status__in=['sent', 'partial', 'overdue']
        ).aggregate(total=Sum('amount_due'))['total'] or 0

        # Outstanding payables
        payables = SupplierBill.objects.filter(
            tenant=tenant,
            status__in=['confirmed', 'partial']
        ).aggregate(total=Sum('amount_due'))['total'] or 0

        # Cash position
        cash_account = Account.objects.filter(tenant=tenant, code='1000').first()
        cash_balance = cash_account.get_current_balance() if cash_account else 0

        # Monthly expenses (simplified)
        from django.db.models import Sum
        expenses = FinancialReportService._calculate_cgs(tenant, month_start, today)

        return Response({
            'monthly_sales': float(monthly_sales),
            'outstanding_receivables': float(receivables),
            'outstanding_payables': float(payables),
            'cash_balance': float(cash_balance),
            'monthly_expenses': float(expenses),
            'net_position': float(cash_balance + receivables - payables)
        })

    @action(detail=False, methods=['post'])
    def export(self, request):
        """Export report to file."""
        report_type = request.data.get('report_type')
        format_type = request.data.get('format', 'pdf')
        params = request.data.get('parameters', {})

        # Generate report data
        tenant = self._get_tenant()

        if report_type == 'trial_balance':
            data = FinancialReportService.trial_balance(
                tenant,
                params.get('start_date'),
                params.get('end_date'),
                params.get('include_zero', False)
            )
        elif report_type == 'profit_loss':
            data = FinancialReportService.profit_loss(
                tenant,
                params.get('start_date'),
                params.get('end_date')
            )
        elif report_type == 'balance_sheet':
            data = FinancialReportService.balance_sheet(
                tenant,
                params.get('as_of_date')
            )
        else:
            return Response({'error': 'Unknown report type'}, status=400)

        # Export based on format
        if format_type == 'pdf':
            exporter = PDFExporter()
            file_content = exporter.generate(report_type, data, tenant)
            content_type = 'application/pdf'
            extension = 'pdf'
        elif format_type == 'excel':
            exporter = ExcelExporter()
            file_content = exporter.generate(report_type, data, tenant)
            content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            extension = 'xlsx'
        else:
            return Response({'error': 'Unsupported format'}, status=400)

        # Create export record
        export = ReportExport.objects.create(
            tenant=tenant,
            report_type=report_type,
            parameters=params,
            format=format_type,
            generated_by=request.user.username
        )

        # Save file
        filename = f"{report_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{extension}"
        export.file.save(filename, file_content)

        return Response({
            'export_id': export.id,
            'download_url': f"/api/reports/download/{export.id}/"
        })


class SavedReportViewSet(viewsets.ModelViewSet):
    serializer_class = SavedReportSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SavedReport.objects.filter(tenant=self.request.user.tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.user.tenant, created_by=self.request.user.username)


class ReportExportViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ReportExportSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ReportExport.objects.filter(tenant=self.request.user.tenant)

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """Download exported file."""
        export = self.get_object()
        export.download_count += 1
        export.save()

        response = HttpResponse(export.file.read())
        response['Content-Type'] = export.get_format_display()
        response['Content-Disposition'] = f'attachment; filename="{export.file.name}"'
        return response