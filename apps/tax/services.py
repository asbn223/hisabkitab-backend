"""
Tax calculation and IRD integration services.
"""
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import Account
from apps.invoicing.models import Invoice
from apps.purchases.models import SupplierBill
from apps.tax.models import TaxPeriod


class VATService:
    """VAT calculation and reporting service."""

    @classmethod
    def create_tax_period(cls, tenant, year_month, period_type='monthly'):
        """Create or get tax period."""
        from .models import TaxPeriod

        # Parse year and month
        year, month = map(int, year_month.split('-'))

        # Calculate dates
        from datetime import date
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)

        # Get fiscal year
        fy = tenant.get_fiscal_year()

        period, created = TaxPeriod.objects.get_or_create(
            tenant=tenant,
            year_month=year_month,
            period_type=period_type,
            defaults={
                'fiscal_year': fy['year'],
                'start_date': start_date,
                'end_date': end_date,
                'bs_start_date': start_date,  # Convert properly
                'bs_end_date': end_date,
                'due_date': end_date,  # Usually 25th of next month
            }
        )
        return period

    @classmethod
    def calculate_period_vat(cls, tax_period):
        """Calculate VAT for a period from invoices and bills."""

        # Sales data
        sales_data = Invoice.objects.filter(
            tenant=tax_period.tenant,
            invoice_date__gte=tax_period.start_date,
            invoice_date__lte=tax_period.end_date,
            status__in=['sent', 'partial', 'paid'],
            is_vat_applicable=True
        ).aggregate(
            taxable=Sum('taxable_amount'),
            vat=Sum('vat_amount'),
            exempt=Sum('exempt_amount'),
            export=Sum('zero_rated_amount')
        )

        # Purchase data
        purchase_data = SupplierBill.objects.filter(
            tenant=tax_period.tenant,
            date__gte=tax_period.start_date,
            date__lte=tax_period.end_date,
            status__in=['confirmed', 'partial', 'paid'],
            is_vat_applicable=True
        ).aggregate(
            taxable=Sum('subtotal'),  # Assuming subtotal is taxable
            vat=Sum('vat_amount')
        )

        tax_period.total_sales_vat = sales_data['vat'] or Decimal('0')
        tax_period.total_purchase_vat = purchase_data['vat'] or Decimal('0')
        tax_period.vat_payable = tax_period.total_sales_vat - tax_period.total_purchase_vat
        tax_period.save()

        return {
            'sales_vat': tax_period.total_sales_vat,
            'purchase_vat': tax_period.total_purchase_vat,
            'net_vat': tax_period.vat_payable,
            'sales_breakdown': sales_data,
            'purchase_breakdown': purchase_data
        }

    @classmethod
    def generate_vat_return(cls, tax_period):
        """Generate VAT Return form data."""
        from .models import VATReturn

        vat_return, created = VATReturn.objects.get_or_create(
            tenant=tax_period.tenant,
            tax_period=tax_period,
            defaults={
                'return_number': f"VAT-{tax_period.year_month}",
                'created_by': 'system'
            }
        )

        # Get detailed calculations
        sales_invoices = Invoice.objects.filter(
            tenant=tax_period.tenant,
            invoice_date__gte=tax_period.start_date,
            invoice_date__lte=tax_period.end_date,
            status__in=['sent', 'partial', 'paid']
        )

        purchases = SupplierBill.objects.filter(
            tenant=tax_period.tenant,
            date__gte=tax_period.start_date,
            date__lte=tax_period.end_date,
            status__in=['confirmed', 'partial', 'paid']
        )

        # Fill return details
        vat_return.local_taxable_sales = sum(
            inv.taxable_amount for inv in sales_invoices
            if inv.invoice_type == 'tax'
        )
        vat_return.local_vat_amount = sum(
            inv.vat_amount for inv in sales_invoices
            if inv.invoice_type == 'tax'
        )
        vat_return.local_exempt_sales = sum(
            inv.exempt_amount for inv in sales_invoices
        )
        vat_return.export_zero_rated = sum(
            inv.zero_rated_amount for inv in sales_invoices
        )

        vat_return.local_taxable_purchases = sum(
            bill.subtotal for bill in purchases if bill.is_vat_applicable
        )
        vat_return.local_vat_paid = sum(
            bill.vat_amount for bill in purchases if bill.is_vat_applicable
        )

        # Get opening credit from previous period
        prev_period = TaxPeriod.objects.filter(
            tenant=tax_period.tenant,
            year_month__lt=tax_period.year_month
        ).order_by('-year_month').first()

        if prev_period:
            prev_return = getattr(prev_period, 'vat_return', None)
            if prev_return:
                vat_return.vat_credit_brought_forward = prev_return.vat_credit_carried_forward

        vat_return.calculate_vat()

        # Create VAT transactions for audit
        cls._create_vat_transactions(tax_period, sales_invoices, purchases)

        return vat_return

    @classmethod
    def _create_vat_transactions(cls, tax_period, sales_invoices, purchases):
        """Create VAT transaction records for detailed reporting."""
        from .models import VATTransaction

        # Sales
        for inv in sales_invoices:
            for line in inv.lines.all():
                VATTransaction.objects.get_or_create(
                    tenant=tax_period.tenant,
                    tax_period=tax_period,
                    transaction_type='sale',
                    source_id=inv.id,
                    defaults={
                        'source_number': inv.invoice_number,
                        'source_date': inv.invoice_date,
                        'party_name': inv.customer.name if inv.customer else inv.billed_name,
                        'party_pan': inv.billed_pan,
                        'vat_type': line.vat_type,
                        'vat_rate': line.vat_rate,
                        'taxable_amount': line.line_total,
                        'vat_amount': line.vat_amount,
                        'total_amount': line.total_with_vat,
                        'ird_bill_id': inv.ird_bill_id,
                        'is_ird_synced': inv.ird_synced
                    }
                )

        # Purchases
        for bill in purchases:
            for line in bill.lines.all():
                VATTransaction.objects.get_or_create(
                    tenant=tax_period.tenant,
                    tax_period=tax_period,
                    transaction_type='purchase',
                    source_id=bill.id,
                    defaults={
                        'source_number': bill.bill_number,
                        'source_date': bill.date,
                        'party_name': bill.supplier.name,
                        'party_pan': bill.supplier.pan_number,
                        'vat_type': line.vat_type,
                        'taxable_amount': line.line_total,
                        'vat_amount': Decimal('0'),  # Calculate if needed
                        'total_amount': line.line_total
                    }
                )

    @classmethod
    def submit_to_ird(cls, vat_return):
        """Submit VAT return to IRD."""
        # Prepare JSON payload as per IRD specs
        payload = {
            "taxpayerPan": vat_return.tenant.pan,
            "fiscalYear": vat_return.tax_period.fiscal_year,
            "returnPeriod": vat_return.tax_period.year_month,
            "returnType": "VAT",
            "salesDetails": {
                "localTaxableSales": float(vat_return.local_taxable_sales),
                "localVatAmount": float(vat_return.local_vat_amount),
                "exemptSales": float(vat_return.local_exempt_sales),
                "exportSales": float(vat_return.export_zero_rated)
            },
            "purchaseDetails": {
                "localTaxablePurchase": float(vat_return.local_taxable_purchases),
                "localVatPaid": float(vat_return.local_vat_paid),
                "importVat": float(vat_return.import_vat)
            },
            "vatCalculation": {
                "outputVat": float(vat_return.vat_output),
                "inputVat": float(vat_return.vat_input),
                "netVat": float(vat_return.net_vat_payable)
            }
        }

        vat_return.ird_json_payload = payload

        # Mock submission - replace with actual API call
        try:
            # response = requests.post(
            #     f"{settings.IRD_API_URL}/vat/returns",
            #     json=payload,
            #     headers={'Authorization': f"Bearer {settings.IRD_TOKEN}"}
            # )
            # Mock success
            vat_return.ird_reference = f"IRD-VAT-{timezone.now().strftime('%Y%m%d%H%M%S')}"
            vat_return.is_finalized = True
            vat_return.finalized_at = timezone.now()
            vat_return.save()

            tax_period = vat_return.tax_period
            tax_period.ird_submitted = True
            tax_period.ird_submitted_at = timezone.now()
            tax_period.save()

            return {'success': True, 'reference': vat_return.ird_reference}

        except Exception as e:
            return {'success': False, 'error': str(e)}


class TDSService:
    """TDS calculation and management."""

    RATES = {
        '88': Decimal('1.50'),   # Contract
        '89': Decimal('15.00'),  # Service
        '90': Decimal('5.00'),   # Interest
        '91': Decimal('10.00'),  # Rent
        '92': Decimal('0.00'),   # Salary (slab based)
        '93': Decimal('15.00'),  # Consultation
        '94': Decimal('5.00'),   # Commission
        '95': Decimal('15.00'),  # Royalty
    }

    @classmethod
    def calculate_tds(cls, section_code, amount):
        """Calculate TDS for given section and amount."""
        rate = cls.RATES.get(section_code, Decimal('0'))
        return amount * (rate / 100)

    @classmethod
    def create_deduction(cls, tenant, section_code, source_doc, amount, party_details):
        """Create TDS deduction record."""
        from .models import TDSSection, TDSDeduction, TaxPeriod

        # Get or create section
        section, _ = TDSSection.objects.get_or_create(
            tenant=tenant,
            section_code=section_code,
            defaults={
                'rate_percent': cls.RATES.get(section_code, Decimal('0')),
                'description': f"TDS Section {section_code}"
            }
        )

        # Get current tax period
        from datetime import datetime
        current_date = timezone.now()
        year_month = current_date.strftime('%Y-%m')

        tax_period = TaxPeriod.objects.filter(
            tenant=tenant,
            year_month=year_month
        ).first()

        tds_amount = cls.calculate_tds(section_code, amount)

        deduction = TDSDeduction.objects.create(
            tenant=tenant,
            tds_section=section,
            tax_period=tax_period,
            source_type=source_doc.__class__.__name__.lower(),
            source_id=source_doc.id,
            document_number=getattr(source_doc, 'bill_number', getattr(source_doc, 'invoice_number', str(source_doc.id))),
            date=timezone.now().date(),
            party_name=party_details.get('name', ''),
            party_pan=party_details.get('pan', ''),
            base_amount=amount,
            tds_rate=section.rate_percent,
            tds_amount=tds_amount,
            net_amount=amount - tds_amount
        )

        # Create accounting entry
        cls._create_tds_accounting(deduction)

        return deduction

    @classmethod
    def _create_tds_accounting(cls, deduction):
        """Create ledger entry for TDS deduction."""
        from apps.accounts.models import Transaction, LedgerEntry

        # Determine accounts based on source
        if deduction.source_type == 'supplierbill':
            payable_account = Account.objects.get(tenant=deduction.tenant, code='2100')
        else:
            payable_account = Account.objects.get(tenant=deduction.tenant, code='6200')

        tds_account = Account.objects.get(tenant=deduction.tenant, code='2210')

        tx = Transaction.objects.create(
            tenant=deduction.tenant,
            reference_number=f"TDS-{deduction.id}",
            date=deduction.date,
            narration=f"TDS deducted {deduction.tds_section.section_code} - {deduction.party_name}",
            status='posted',
            source_type='tds_deduction',
            source_id=deduction.id
        )

        # Debit Expense/Payable (full amount)
        LedgerEntry.objects.create(
            tenant=deduction.tenant,
            transaction=tx,
            account=payable_account,
            debit=deduction.base_amount,
            credit=Decimal('0')
        )

        # Credit TDS Payable (liability)
        LedgerEntry.objects.create(
            tenant=deduction.tenant,
            transaction=tx,
            account=tds_account,
            debit=Decimal('0'),
            credit=deduction.tds_amount
        )

        # Credit Net to Party (reduced payment)
        LedgerEntry.objects.create(
            tenant=deduction.tenant,
            transaction=tx,
            account=payable_account,
            debit=Decimal('0'),
            credit=deduction.net_amount
        )

        deduction.transaction = tx
        deduction.save()