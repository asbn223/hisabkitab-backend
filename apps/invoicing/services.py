"""
IRD Integration and PDF generation services.
"""
import requests
import base64
import qrcode
import io
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from weasyprint import HTML, CSS
from decimal import Decimal


class IRDService:
    """
    Nepal Inland Revenue Department API integration.
    Real-time invoice submission for VAT compliance.
    """

    BASE_URL = getattr(settings, 'IRD_API_URL', "https://api.ird.gov.np/api/bill")

    @classmethod
    def submit_invoice(cls, invoice):
        """
        Submit invoice to IRD and store returned QR code.
        """
        if not invoice.is_vat_applicable:
            return {'success': False, 'error': 'Not a VAT invoice'}

        payload = {
            "username": settings.IRD_USERNAME,
            "password": settings.IRD_PASSWORD,
            "seller_pan": invoice.tenant.pan,
            "buyer_pan": invoice.billed_pan or "",
            "buyer_name": invoice.billed_name,
            "fiscal_year": invoice.fiscal_year,
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.date.isoformat(),
            "total_sales": float(invoice.subtotal),
            "taxable_sales_vat": float(invoice.taxable_amount),
            "vat_amount": float(invoice.vat_amount),
            "excise_amount": 0,
            "discount_amount": float(invoice.discount_amount),
            "total_amount": float(invoice.total_amount),
            "is_printed": True,
            "printed_time": invoice.created_at.isoformat(),
            "items": [
                {
                    "description": line.description,
                    "quantity": float(line.quantity),
                    "unit": line.unit,
                    "unit_price": float(line.unit_price),
                    "total": float(line.line_total),
                    "vat_rate": float(line.vat_rate),
                    "vat_amount": float(line.vat_amount)
                }
                for line in invoice.lines.all()
            ]
        }

        try:
            response = requests.post(
                f"{cls.BASE_URL}/submit",
                json=payload,
                timeout=30,
                headers={'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            data = response.json()

            # Store IRD response
            invoice.ird_bill_id = data.get('bill_id')
            invoice.ird_qr_data = data.get('qr_data', '')
            invoice.ird_synced = True
            invoice.ird_synced_at = timezone.now()
            invoice.save()

            return {'success': True, 'data': data}

        except requests.exceptions.RequestException as e:
            invoice.ird_sync_error = str(e)
            invoice.save()
            return {'success': False, 'error': str(e)}

    @classmethod
    def verify_invoice(cls, bill_id):
        """Verify invoice status with IRD."""
        try:
            response = requests.get(
                f"{cls.BASE_URL}/verify/{bill_id}",
                timeout=10
            )
            return response.json()
        except requests.exceptions.RequestException as e:
            return {'error': str(e)}


class PDFService:
    """
    Invoice PDF generation with VAT compliance formatting.
    """

    @classmethod
    def generate_invoice_pdf(cls, invoice):
        """Generate PDF from HTML template."""
        html_string = cls._get_html(invoice)

        css_string = """
        @page { size: A4; margin: 15mm; }
        body { font-family: 'Helvetica', 'Arial', sans-serif; font-size: 10pt; color: #333; }
        .header { border-bottom: 3px solid #2c3e50; padding-bottom: 15px; margin-bottom: 20px; }
        .company-name { font-size: 20pt; font-weight: bold; color: #2c3e50; }
        .invoice-title { font-size: 18pt; color: #e74c3c; text-align: right; }
        .info-grid { display: flex; justify-content: space-between; margin: 20px 0; }
        .info-box { width: 48%; }
        .info-box h4 { margin: 0 0 10px 0; color: #2c3e50; border-bottom: 1px solid #ecf0f1; padding-bottom: 5px; }
        table.items { width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 9pt; }
        table.items th { background: #2c3e50; color: white; padding: 8px; text-align: left; }
        table.items td { padding: 8px; border-bottom: 1px solid #ecf0f1; }
        .text-right { text-align: right; }
        .totals-box { width: 40%; margin-left: auto; margin-top: 20px; }
        .totals-box table { width: 100%; }
        .totals-box td { padding: 5px; }
        .grand-total { font-size: 12pt; font-weight: bold; background: #ecf0f1; }
        .vat-summary { margin-top: 20px; padding: 10px; background: #f8f9fa; font-size: 9pt; }
        .footer { margin-top: 40px; font-size: 8pt; color: #7f8c8d; text-align: center; }
        .qr-section { text-align: center; margin-top: 30px; }
        .ird-badge { color: #27ae60; font-weight: bold; }
        .watermark { position: fixed; top: 40%; left: 30%; transform: rotate(-45deg); 
                    font-size: 60pt; color: rgba(231, 76, 60, 0.1); font-weight: bold; }
        """

        html = HTML(string=html_string)
        css = CSS(string=css_string)
        return html.write_pdf(stylesheets=[css])

    @classmethod
    def _get_html(cls, invoice):
        """Generate HTML content."""
        # Generate QR code if IRD synced
        qr_image = ""
        if invoice.ird_synced and invoice.ird_qr_data:
            qr = qrcode.QRCode(version=1, box_size=6, border=2)
            qr.add_data(invoice.ird_qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            qr_b64 = base64.b64encode(buffer.getvalue()).decode()
            qr_image = f'<img src="data:image/png;base64,{qr_b64}" width="120">'

        lines_html = ""
        for i, line in enumerate(invoice.lines.all(), 1):
            lines_html += f"""
            <tr>
                <td>{i}</td>
                <td>{line.description}</td>
                <td>{line.sku or '-'}</td>
                <td class="text-right">{line.quantity}</td>
                <td>{line.unit}</td>
                <td class="text-right">{line.unit_price:,.2f}</td>
                <td class="text-right">{line.line_discount:,.2f}</td>
                <td class="text-right">{line.line_total:,.2f}</td>
                <td class="text-right">{line.vat_rate}%</td>
                <td class="text-right">{line.vat_amount:,.2f}</td>
                <td class="text-right"><strong>{line.total_with_vat:,.2f}</strong></td>
            </tr>
            """

        ird_status = ""
        if invoice.ird_synced:
            ird_status = f'<div class="ird-badge">✓ IRD Verified (Bill ID: {invoice.ird_bill_id})</div>'

        return f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"></head>
        <body>
            <div class="header">
                <div style="float: left;">
                    <div class="company-name">{invoice.tenant.name}</div>
                    <div>{invoice.tenant.address}</div>
                    <div>PAN: {invoice.tenant.pan or 'N/A'}</div>
                </div>
                <div style="float: right; text-align: right;">
                    <div class="invoice-title">TAX INVOICE</div>
                    <div>{ird_status}</div>
                </div>
                <div style="clear: both;"></div>
            </div>

            <div class="info-grid">
                <div class="info-box">
                    <h4>Bill To:</h4>
                    <strong>{invoice.billed_name}</strong><br>
                    {invoice.billed_address or ''}<br>
                    PAN: {invoice.billed_pan or 'N/A'}<br>
                    {invoice.customer.phone or ''}
                </div>
                <div class="info-box" style="text-align: right;">
                    <h4>Invoice Details:</h4>
                    <strong>Invoice #:</strong> {invoice.invoice_number}<br>
                    <strong>Date:</strong> {invoice.bs_date} ({invoice.date})<br>
                    <strong>Due Date:</strong> {invoice.bs_due_date}<br>
                    <strong>Fiscal Year:</strong> {invoice.fiscal_year}<br>
                    <strong>Reference:</strong> {invoice.manual_reference or '-'}
                </div>
            </div>

            <table class="items">
                <thead>
                    <tr>
                        <th>S.N.</th>
                        <th>Description</th>
                        <th>SKU</th>
                        <th class="text-right">Qty</th>
                        <th>Unit</th>
                        <th class="text-right">Rate</th>
                        <th class="text-right">Disc</th>
                        <th class="text-right">Amount</th>
                        <th class="text-right">VAT%</th>
                        <th class="text-right">VAT Amt</th>
                        <th class="text-right">Total</th>
                    </tr>
                </thead>
                <tbody>
                    {lines_html}
                </tbody>
            </table>

            <div class="vat-summary">
                <strong>VAT Summary:</strong> 
                Taxable: Rs. {invoice.taxable_amount:,.2f} | 
                Exempt: Rs. {invoice.exempt_amount:,.2f} | 
                Zero-rated: Rs. {invoice.zero_rated_amount:,.2f}
            </div>

            <div class="totals-box">
                <table>
                    <tr><td>Subtotal:</td><td class="text-right">Rs. {invoice.subtotal:,.2f}</td></tr>
                    {f'<tr><td>Discount:</td><td class="text-right">Rs. {invoice.discount_amount:,.2f}</td></tr>' if invoice.discount_amount > 0 else ''}
                    <tr><td>VAT ({invoice.vat_rate}%):</td><td class="text-right">Rs. {invoice.vat_amount:,.2f}</td></tr>
                    <tr class="grand-total"><td>Grand Total:</td><td class="text-right">Rs. {invoice.total_amount:,.2f}</td></tr>
                    <tr><td>Amount Paid:</td><td class="text-right">Rs. {invoice.amount_paid:,.2f}</td></tr>
                    <tr style="color: {'red' if invoice.amount_due > 0 else 'green'};">
                        <td><strong>Amount Due:</strong></td>
                        <td class="text-right"><strong>Rs. {invoice.amount_due:,.2f}</strong></td>
                    </tr>
                </table>
            </div>

            <div class="qr-section">
                {qr_image}
                {f'<p>Scan to verify with IRD</p>' if qr_image else ''}
            </div>

            <div class="footer">
                <p><strong>Terms:</strong> {invoice.terms or 'Payment due within 30 days.'}</p>
                <p>{invoice.notes or ''}</p>
                <p style="margin-top: 20px;">This is a computer generated invoice.</p>
            </div>

            {f'<div class="watermark">{invoice.status.upper()}</div>' if invoice.status != 'paid' else ''}
        </body>
        </html>
        """