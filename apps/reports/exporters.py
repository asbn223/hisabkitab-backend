"""
Report export generators (PDF, Excel).
"""
import io
from decimal import Decimal

from django.template.loader import render_to_string


class PDFExporter:
    """Generate PDF reports using WeasyPrint or similar."""

    def generate(self, report_type, data, tenant):
        """Generate PDF from report data."""
        # This is a placeholder - actual implementation would use WeasyPrint
        # or ReportLab to generate PDFs

        template_map = {
            'trial_balance': 'reports/trial_balance.html',
            'profit_loss': 'reports/profit_loss.html',
            'balance_sheet': 'reports/balance_sheet.html',
        }

        template = template_map.get(report_type, 'reports/generic.html')

        html_string = render_to_string(template, {
            'data': data,
            'tenant': tenant,
            'generated_at': datetime.now()
        })

        # Convert to PDF (pseudo-code)
        # from weasyprint import HTML
        # pdf = HTML(string=html_string).write_pdf()

        # Return as ContentFile for now
        from django.core.files.base import ContentFile
        return ContentFile(html_string.encode())  # Placeholder


class ExcelExporter:
    """Generate Excel reports using openpyxl."""

    def generate(self, report_type, data, tenant):
        """Generate Excel from report data."""
        try:
            import openpyxl
            from openpyxl.styles import Font, Alignment, PatternFill
        except ImportError:
            raise Exception("openpyxl required for Excel export")

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = report_type.replace('_', ' ').title()

        # Add headers based on report type
        if report_type == 'trial_balance':
            self._add_trial_balance_sheet(ws, data)
        elif report_type == 'profit_loss':
            self._add_profit_loss_sheet(ws, data)
        elif report_type == 'balance_sheet':
            self._add_balance_sheet_sheet(ws, data)

        # Save to buffer
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        from django.core.files.base import ContentFile
        return ContentFile(buffer.read())

    def _add_trial_balance_sheet(self, ws, data):
        """Add Trial Balance to worksheet."""
        # Headers
        headers = ['Account Code', 'Account Name', 'Opening Debit', 'Opening Credit',
                   'Period Debit', 'Period Credit', 'Closing Debit', 'Closing Credit']
        ws.append(headers)

        # Data
        for account in data.get('accounts', []):
            ws.append([
                account['account_code'],
                account['account_name'],
                account['opening_debit'],
                account['opening_credit'],
                account['period_debit'],
                account['period_credit'],
                account['closing_debit'],
                account['closing_credit']
            ])

        # Totals
        ws.append(['', 'TOTAL', '', '', data['total_debit'], data['total_credit'], '', ''])

    def _add_profit_loss_sheet(self, ws, data):
        """Add P&L to worksheet."""
        ws.append(['PROFIT & LOSS STATEMENT'])
        ws.append([f"Period: {data['start_date']} to {data['end_date']}"])
        ws.append([])

        ws.append(['INCOME'])
        for item in data['income']['accounts']:
            ws.append([item['account_name'], item['amount']])
        ws.append(['Total Income', data['income']['total']])
        ws.append([])

        ws.append(['EXPENSES'])
        for item in data['expenses']['accounts']:
            ws.append([item['account_name'], item['amount']])
        ws.append(['Total Expenses', data['expenses']['total']])
        ws.append([])

        ws.append(['NET PROFIT', data['net_profit']])

    def _add_balance_sheet_sheet(self, ws, data):
        """Add Balance Sheet to worksheet."""
        ws.append(['BALANCE SHEET'])
        ws.append([f"As of: {data['as_of_date']}"])
        ws.append([])

        ws.append(['ASSETS'])
        for item in data['assets']['accounts']:
            ws.append([item['account_name'], item['balance']])
        ws.append(['Total Assets', data['assets']['total']])
        ws.append([])

        ws.append(['LIABILITIES'])
        for item in data['liabilities']['accounts']:
            ws.append([item['account_name'], item['balance']])
        ws.append(['Total Liabilities', data['liabilities']['total']])
        ws.append([])

        ws.append(['EQUITY'])
        for item in data['equity']['accounts']:
            ws.append([item['account_name'], item['balance']])
        ws.append(['Total Equity', data['equity']['total']])