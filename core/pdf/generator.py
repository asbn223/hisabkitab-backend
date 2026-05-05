# apps/core/pdf/generator.py
"""
PDF generation using WeasyPrint.
Optimized for Nepali fonts and IRD compliance.
"""
import os
import io
import base64
import hashlib
from datetime import datetime
from typing import Optional

from weasyprint import HTML, CSS
from django.template.loader import render_to_string
from django.conf import settings
import boto3
import qrcode
from PIL import Image

from core.bs_date import format_bs_date, to_nepali_digits


class BasePDFGenerator:
    """Base class for PDF generation."""

    def __init__(self):
        self.s3 = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,
        ) if settings.AWS_ACCESS_KEY_ID else None

    def _upload_to_s3(self, pdf_bytes: bytes, key: str,
                      metadata: dict = None) -> str:
        """Upload PDF to S3 and return presigned URL."""
        if not self.s3:
            raise RuntimeError("S3 not configured")

        extra_args = {
            'ContentType': 'application/pdf',
            'ServerSideEncryption': 'AES256',
        }

        if metadata:
            extra_args['Metadata'] = {
                k: str(v) for k, v in metadata.items()
            }

        self.s3.put_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=key,
            Body=pdf_bytes,
            **extra_args
        )

        # Generate presigned URL (1 hour expiry)
        url = self.s3.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                'Key': key
            },
            ExpiresIn=3600
        )

        return url

    def _generate_qr_code(self, data: str, size: int = 100) -> str:
        """Generate QR code as base64 data URI."""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        img = img.resize((size, size), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        img_str = base64.b64encode(buffer.getvalue()).decode()

        return f"data:image/png;base64,{img_str}"


class InvoicePDFGenerator(BasePDFGenerator):
    """Generator for VAT invoices."""

    def generate_vat_invoice(self, invoice_id: int,
                             save_to_s3: bool = True) -> dict:
        """
        Generate IRD-compliant VAT invoice PDF.

        Args:
            invoice_id: Invoice ID
            save_to_s3: Whether to upload to S3

        Returns:
            Dict with pdf_url, file_path, page_count
        """
        from apps.invoicing.models import Invoice

        invoice = Invoice.objects.select_related('tenant').prefetch_related(
            'lines', 'lines__item'
        ).get(id=invoice_id)

        # Generate QR code data (IRD format)
        qr_data = self._generate_ird_qr_data(invoice)
        qr_code = self._generate_qr_code(qr_data, size=120)

        # Prepare context
        context = {
            'invoice': invoice,
            'lines': list(invoice.lines.all()),
            'tenant': invoice.tenant,
            'qr_code': qr_code,
            'qr_data': qr_data,
            'bs_date_formatted': format_bs_date(invoice.bs_date, use_nepali_digits=True),
            'generated_at': datetime.now().isoformat(),
            'total_in_words': self._number_to_words(float(invoice.total_amount)),
        }

        # Render HTML
        html_string = render_to_string('pdf/vat_invoice.html', context)

        # CSS with embedded fonts
        css_path = settings.BASE_DIR / 'templates' / 'pdf' / 'styles.css'
        css = CSS(filename=str(css_path)) if css_path.exists() else None

        # Generate PDF
        html = HTML(string=html_string, base_url=str(settings.BASE_DIR))
        pdf_bytes = html.write_pdf(stylesheets=[css] if css else None)

        result = {
            'pdf_bytes': pdf_bytes,
            'page_count': len(html.render([css] if css else None).pages) if css else 1,
        }

        if save_to_s3:
            key = f"tenants/{invoice.tenant_id}/invoices/{invoice.id}_{invoice.invoice_number}.pdf"
            url = self._upload_to_s3(
                pdf_bytes,
                key,
                metadata={
                    'tenant-id': invoice.tenant_id,
                    'invoice-id': invoice.id,
                    'invoice-number': invoice.invoice_number,
                    'total-amount': str(invoice.total_amount),
                }
            )
            result['pdf_url'] = url
            result['s3_key'] = key

        return result

    def generate_thermal_receipt(self, invoice_id: int) -> bytes:
        """
        Generate thermal printer optimized receipt (80mm width).

        Returns:
            PDF bytes for thermal printing
        """
        from apps.invoicing.models import Invoice

        invoice = Invoice.objects.select_related('tenant').get(id=invoice_id)

        context = {
            'invoice': invoice,
            'tenant': invoice.tenant,
            'lines': list(invoice.lines.all()),
            'narrow': True,  # 80mm width flag
        }

        html_string = render_to_string('pdf/thermal_receipt.html', context)

        # Custom CSS for thermal (58mm or 80mm)
        css = CSS(string='''
            @page { size: 80mm auto; margin: 0; }
            body { font-family: monospace; font-size: 10pt; width: 80mm; }
            .center { text-align: center; }
            .right { text-align: right; }
            table { width: 100%; border-collapse: collapse; }
            td { padding: 2px 0; }
            .dashed { border-top: 1px dashed #000; margin: 5px 0; }
        ''')

        html = HTML(string=html_string)
        return html.write_pdf(stylesheets=[css])

    def _generate_ird_qr_data(self, invoice) -> str:
        """
        Generate QR code data per IRD Nepal specifications.

        Format: InvoiceNum|SellerPAN|Total|VAT|Date|Hash
        """
        from core.decimal.decimal_config import fiscal_round

        # Create pipe-delimited string
        data_parts = [
            invoice.invoice_number,
            invoice.tenant.pan or '',
            str(fiscal_round(invoice.total_amount)),
            str(fiscal_round(invoice.vat_amount)),
            invoice.bs_date,
        ]

        base = '|'.join(data_parts)

        # Add simple hash for integrity
        hash_val = hashlib.md5(f"{base}|{settings.SECRET_KEY[:16]}".encode()).hexdigest()[:8]

        return f"{base}|{hash_val}"

    def _number_to_words(self, number: float) -> str:
        """Convert number to words (simplified)."""
        # For production, use num2words library with Nepali support
        return f"NPR {number:,.2f} Only"


class ReportPDFGenerator(BasePDFGenerator):
    """Generator for financial reports."""

    def generate_trial_balance(self, tenant_id: int, as_of: str = None) -> dict:
        """Generate Trial Balance PDF."""
        from apps.accounts.models import Account, LedgerEntry, Transaction
        from apps.tenants.models import Tenant
        from django.db.models import Sum, Q
        from decimal import Decimal

        tenant = Tenant.objects.get(id=tenant_id)

        # Get all active accounts
        accounts = Account.objects.filter(
            tenant=tenant,
            is_active=True
        ).order_by('code')

        # Calculate balances
        report_data = []
        total_debit = Decimal('0')
        total_credit = Decimal('0')

        for account in accounts:
            # Sum ledger entries
            entries = LedgerEntry.objects.filter(
                tenant=tenant,
                account=account,
                transaction__status='posted'
            )

            if as_of:
                entries = entries.filter(transaction__date__lte=as_of)

            sums = entries.aggregate(
                total_debit=Sum('debit'),
                total_credit=Sum('credit')
            )

            debit = sums['total_debit'] or Decimal('0')
            credit = sums['total_credit'] or Decimal('0')

            # Add opening balance
            balance = account.opening_balance + debit - credit

            if balance != 0:
                if balance > 0:
                    debit_bal = balance
                    credit_bal = Decimal('0')
                    total_debit += balance
                else:
                    debit_bal = Decimal('0')
                    credit_bal = abs(balance)
                    total_credit += abs(balance)

                report_data.append({
                    'code': account.code,
                    'name': account.name,
                    'type': account.type,
                    'debit': debit_bal,
                    'credit': credit_bal,
                })

        context = {
            'tenant': tenant,
            'as_of': as_of or datetime.now().date(),
            'accounts': report_data,
            'total_debit': total_debit,
            'total_credit': total_credit,
            'generated_at': datetime.now(),
        }

        html_string = render_to_string('pdf/trial_balance.html', context)
        html = HTML(string=html_string)
        pdf_bytes = html.write_pdf()

        key = f"tenants/{tenant_id}/reports/trial_balance_{as_of or 'current'}.pdf"
        url = self._upload_to_s3(pdf_bytes, key, {
            'tenant-id': tenant_id,
            'report-type': 'trial-balance',
            'as-of': as_of or 'current',
        })

        return {
            'pdf_url': url,
            's3_key': key,
            'total_debit': str(total_debit),
            'total_credit': str(total_credit),
        }