"""
Financial report generation services.
"""
from decimal import Decimal
from datetime import date, timedelta
from django.db.models import Sum, Q
from django.utils import timezone
from collections import defaultdict

from apps.accounts.models import Account, Transaction, LedgerEntry
from apps.invoicing.models import Invoice, InvoiceLine
from apps.purchases.models import PurchaseOrder, SupplierBill
from apps.inventory.models import InventoryItem, StockMovement


class FinancialReportService:
    """Core financial reporting service."""

    @staticmethod
    def get_date_range(period, fiscal_year=None, start_date=None, end_date=None):
        """Convert period to date range."""
        from apps.tenants.models import Tenant

        today = timezone.now().date()

        if period == 'current_month':
            start = today.replace(day=1)
            if today.month == 12:
                end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        elif period == 'current_quarter':
            quarter = (today.month - 1) // 3 + 1
            start = today.replace(month=(quarter - 1) * 3 + 1, day=1)
            if quarter == 4:
                end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                end = today.replace(month=quarter * 3 + 1, day=1) - timedelta(days=1)
        elif period == 'current_fy':
            # Approximate - should use actual fiscal year dates
            start = today.replace(month=4, day=1)
            if today.month < 4:
                start = start.replace(year=today.year - 1)
            end = today
        elif period == 'custom' and start_date and end_date:
            start = start_date
            end = end_date
        else:
            start = today.replace(day=1)
            end = today

        return start, end

    @classmethod
    def trial_balance(cls, tenant, start_date, end_date, include_zero=False):
        """
        Generate Trial Balance report.
        Shows all accounts with opening balance, movements, and closing balance.
        """
        accounts = Account.objects.filter(tenant=tenant, is_active=True).order_by('code')

        report_data = []
        total_debit = Decimal('0')
        total_credit = Decimal('0')

        for account in accounts:
            # Opening balance (before start date)
            opening_entries = LedgerEntry.objects.filter(
                tenant=tenant,
                account=account,
                transaction__date__lt=start_date,
                transaction__status='posted'
            )

            opening_debit = opening_entries.aggregate(s=Sum('debit'))['s'] or Decimal('0')
            opening_credit = opening_entries.aggregate(s=Sum('credit'))['s'] or Decimal('0')
            opening_balance = account.opening_balance + opening_debit - opening_credit

            # Period movements
            period_entries = LedgerEntry.objects.filter(
                tenant=tenant,
                account=account,
                transaction__date__gte=start_date,
                transaction__date__lte=end_date,
                transaction__status='posted'
            )

            period_debit = period_entries.aggregate(s=Sum('debit'))['s'] or Decimal('0')
            period_credit = period_entries.aggregate(s=Sum('credit'))['s'] or Decimal('0')

            # Closing balance
            closing_balance = opening_balance + period_debit - period_credit

            # Skip zero balances if not included
            if not include_zero and opening_balance == 0 and period_debit == 0 and period_credit == 0:
                continue

            # Determine display side based on account type
            if account.type in ('asset', 'expense'):
                normal_balance = 'debit'
            else:
                normal_balance = 'credit'

            report_data.append({
                'account_code': account.code,
                'account_name': account.name,
                'account_type': account.type,
                'opening_balance': float(opening_balance),
                'opening_debit': float(opening_balance) if opening_balance > 0 else 0,
                'opening_credit': float(abs(opening_balance)) if opening_balance < 0 else 0,
                'period_debit': float(period_debit),
                'period_credit': float(period_credit),
                'closing_balance': float(closing_balance),
                'closing_debit': float(closing_balance) if closing_balance > 0 else 0,
                'closing_credit': float(abs(closing_balance)) if closing_balance < 0 else 0,
                'normal_balance': normal_balance
            })

            total_debit += period_debit
            total_credit += period_credit

        return {
            'report_type': 'trial_balance',
            'start_date': str(start_date),
            'end_date': str(end_date),
            'accounts': report_data,
            'total_debit': float(total_debit),
            'total_credit': float(total_credit),
            'is_balanced': abs(total_debit - total_credit) < Decimal('0.01')
        }

    @classmethod
    def profit_loss(cls, tenant, start_date, end_date, compare_previous=False):
        """
        Generate Profit & Loss Statement (Income Statement).
        """
        # Income accounts (Credit increases income)
        income_accounts = Account.objects.filter(
            tenant=tenant,
            type='income',
            is_active=True
        ).order_by('code')

        income_data = []
        total_income = Decimal('0')

        for account in income_accounts:
            entries = LedgerEntry.objects.filter(
                tenant=tenant,
                account=account,
                transaction__date__gte=start_date,
                transaction__date__lte=end_date,
                transaction__status='posted'
            )

            credit = entries.aggregate(s=Sum('credit'))['s'] or Decimal('0')
            debit = entries.aggregate(s=Sum('debit'))['s'] or Decimal('0')
            net = credit - debit  # Credit - Debit for income

            if net != 0:
                income_data.append({
                    'account_code': account.code,
                    'account_name': account.name,
                    'amount': float(net),
                    'is_positive': net > 0
                })
                total_income += net

        # Expense accounts (Debit increases expense)
        expense_accounts = Account.objects.filter(
            tenant=tenant,
            type='expense',
            is_active=True
        ).order_by('code')

        expense_data = []
        total_expense = Decimal('0')

        for account in expense_accounts:
            entries = LedgerEntry.objects.filter(
                tenant=tenant,
                account=account,
                transaction__date__gte=start_date,
                transaction__date__lte=end_date,
                transaction__status='posted'
            )

            debit = entries.aggregate(s=Sum('debit'))['s'] or Decimal('0')
            credit = entries.aggregate(s=Sum('credit'))['s'] or Decimal('0')
            net = debit - credit  # Debit - Credit for expense

            if net != 0:
                expense_data.append({
                    'account_code': account.code,
                    'account_name': account.name,
                    'amount': float(net),
                    'is_positive': net > 0
                })
                total_expense += net

        # COGS calculation (if not already in expenses)
        cogs = cls._calculate_cogs(tenant, start_date, end_date)

        gross_profit = total_income - cogs
        net_profit = total_income - total_expense - cogs

        # Previous period comparison
        comparison = {}
        if compare_previous:
            period_length = (end_date - start_date).days
            prev_start = start_date - timedelta(days=period_length)
            prev_end = start_date - timedelta(days=1)

            prev_data = cls.profit_loss(tenant, prev_start, prev_end, compare_previous=False)
            comparison = {
                'previous_period': f"{prev_start} to {prev_end}",
                'previous_net_profit': prev_data['net_profit'],
                'variance': float(net_profit) - prev_data['net_profit'],
                'variance_percent': ((float(net_profit) - prev_data['net_profit']) / prev_data['net_profit'] * 100) if
                prev_data['net_profit'] != 0 else 0
            }

        return {
            'report_type': 'profit_loss',
            'start_date': str(start_date),
            'end_date': str(end_date),
            'income': {
                'accounts': income_data,
                'total': float(total_income)
            },
            'cogs': float(cogs),
            'gross_profit': float(gross_profit),
            'expenses': {
                'accounts': expense_data,
                'total': float(total_expense)
            },
            'net_profit': float(net_profit),
            'is_profitable': net_profit > 0,
            'comparison': comparison
        }

    @classmethod
    def _calculate_cogs(cls, tenant, start_date, end_date):
        """Calculate Cost of Goods Sold."""
        # Opening stock + Purchases - Closing stock
        # Simplified version - can be enhanced with actual inventory valuation

        stock_movements = StockMovement.objects.filter(
            tenant=tenant,
            date__gte=start_date,
            date__lte=end_date
        )

        cogs = Decimal('0')
        for movement in stock_movements:
            if movement.type in ('issue', 'return_out', 'production_out'):
                cogs += movement.total_cost or Decimal('0')

        return cogs

    @classmethod
    def balance_sheet(cls, tenant, as_of_date):
        """
        Generate Balance Sheet (Statement of Financial Position).
        """
        # Assets
        assets = Account.objects.filter(
            tenant=tenant,
            type='asset',
            is_active=True
        ).order_by('code')

        asset_data = []
        total_assets = Decimal('0')

        for account in assets:
            balance = account.get_current_balance(as_of_date)
            if balance != 0:
                asset_data.append({
                    'account_code': account.code,
                    'account_name': account.name,
                    'balance': float(balance),
                    'category': cls._get_asset_category(account.code)
                })
                total_assets += balance

        # Liabilities
        liabilities = Account.objects.filter(
            tenant=tenant,
            type='liability',
            is_active=True
        ).order_by('code')

        liability_data = []
        total_liabilities = Decimal('0')

        for account in liabilities:
            balance = account.get_current_balance(as_of_date)
            if balance != 0:
                liability_data.append({
                    'account_code': account.code,
                    'account_name': account.name,
                    'balance': float(abs(balance)),  # Liabilities normally credit
                    'category': cls._get_liability_category(account.code)
                })
                total_liabilities += abs(balance)

        # Equity
        equity = Account.objects.filter(
            tenant=tenant,
            type='equity',
            is_active=True
        ).order_by('code')

        equity_data = []
        total_equity = Decimal('0')

        # Add retained earnings calculation
        retained_earnings = cls._calculate_retained_earnings(tenant, as_of_date)

        for account in equity:
            balance = account.get_current_balance(as_of_date)
            if balance != 0:
                equity_data.append({
                    'account_code': account.code,
                    'account_name': account.name,
                    'balance': float(abs(balance)),
                    'category': 'equity'
                })
                total_equity += abs(balance)

        # Add retained earnings
        equity_data.append({
            'account_code': 'RE',
            'account_name': 'Retained Earnings',
            'balance': float(retained_earnings),
            'category': 'retained_earnings'
        })
        total_equity += retained_earnings

        total_liabilities_equity = total_liabilities + total_equity

        return {
            'report_type': 'balance_sheet',
            'as_of_date': str(as_of_date),
            'assets': {
                'accounts': asset_data,
                'total': float(total_assets),
                'current_assets': sum(a['balance'] for a in asset_data if a['category'] == 'current'),
                'fixed_assets': sum(a['balance'] for a in asset_data if a['category'] == 'fixed')
            },
            'liabilities': {
                'accounts': liability_data,
                'total': float(total_liabilities),
                'current_liabilities': sum(l['balance'] for l in liability_data if l['category'] == 'current'),
                'long_term': sum(l['balance'] for l in liability_data if l['category'] == 'long_term')
            },
            'equity': {
                'accounts': equity_data,
                'total': float(total_equity)
            },
            'total_liabilities_equity': float(total_liabilities_equity),
            'is_balanced': abs(total_assets - total_liabilities_equity) < Decimal('0.01')
        }

    @classmethod
    def _get_asset_category(cls, code):
        """Categorize asset by account code."""
        if code.startswith('10') or code.startswith('11'):
            return 'current'
        elif code.startswith('12'):
            return 'receivables'
        elif code.startswith('15') or code.startswith('16'):
            return 'fixed'
        return 'other'

    @classmethod
    def _get_liability_category(cls, code):
        """Categorize liability by account code."""
        if code.startswith('21') or code.startswith('22'):
            return 'current'
        elif code.startswith('23') or code.startswith('24'):
            return 'long_term'
        return 'other'

    @classmethod
    def _calculate_retained_earnings(cls, tenant, as_of_date):
        """Calculate retained earnings up to date."""
        # Sum of all income - all expenses since beginning
        income_accounts = Account.objects.filter(tenant=tenant, type='income')
        expense_accounts = Account.objects.filter(tenant=tenant, type='expense')

        total_income = Decimal('0')
        for acc in income_accounts:
            bal = acc.get_current_balance(as_of_date)
            total_income += bal  # Credit balance

        total_expense = Decimal('0')
        for acc in expense_accounts:
            bal = acc.get_current_balance(as_of_date)
            total_expense += bal  # Debit balance

        return total_income - total_expense

    @classmethod
    def cash_flow(cls, tenant, start_date, end_date):
        """
        Generate Cash Flow Statement.
        """
        # Operating Activities
        operating_in = LedgerEntry.objects.filter(
            tenant=tenant,
            account__code__startswith='10',  # Cash/Bank accounts
            transaction__date__gte=start_date,
            transaction__date__lte=end_date,
            debit__gt=0
        ).exclude(
            transaction__source_type__in=['capital', 'loan', 'investment']
        ).aggregate(s=Sum('debit'))['s'] or Decimal('0')

        operating_out = LedgerEntry.objects.filter(
            tenant=tenant,
            account__code__startswith='10',
            transaction__date__gte=start_date,
            transaction__date__lte=end_date,
            credit__gt=0
        ).exclude(
            transaction__source_type__in=['capital', 'loan', 'investment', 'dividend']
        ).aggregate(s=Sum('credit'))['s'] or Decimal('0')

        # Investing Activities
        investing_in = LedgerEntry.objects.filter(
            tenant=tenant,
            account__code__startswith='10',
            transaction__date__gte=start_date,
            transaction__date__lte=end_date,
            debit__gt=0,
            transaction__source_type='investment'
        ).aggregate(s=Sum('debit'))['s'] or Decimal('0')

        investing_out = LedgerEntry.objects.filter(
            tenant=tenant,
            account__code__startswith='10',
            transaction__date__gte=start_date,
            transaction__date__lte=end_date,
            credit__gt=0,
            transaction__source_type='asset_purchase'
        ).aggregate(s=Sum('credit'))['s'] or Decimal('0')

        # Financing Activities
        financing_in = LedgerEntry.objects.filter(
            tenant=tenant,
            account__code__startswith='10',
            transaction__date__gte=start_date,
            transaction__date__lte=end_date,
            debit__gt=0,
            transaction__source_type__in=['capital', 'loan']
        ).aggregate(s=Sum('debit'))['s'] or Decimal('0')

        financing_out = LedgerEntry.objects.filter(
            tenant=tenant,
            account__code__startswith='10',
            transaction__date__gte=start_date,
            transaction__date__lte=end_date,
            credit__gt=0,
            transaction__source_type__in=['loan_repayment', 'dividend']
        ).aggregate(s=Sum('credit'))['s'] or Decimal('0')

        net_operating = operating_in - operating_out
        net_investing = investing_in - investing_out
        net_financing = financing_in - financing_out

        return {
            'report_type': 'cash_flow',
            'start_date': str(start_date),
            'end_date': str(end_date),
            'operating_activities': {
                'cash_in': float(operating_in),
                'cash_out': float(operating_out),
                'net': float(net_operating)
            },
            'investing_activities': {
                'cash_in': float(investing_in),
                'cash_out': float(investing_out),
                'net': float(net_investing)
            },
            'financing_activities': {
                'cash_in': float(financing_in),
                'cash_out': float(financing_out),
                'net': float(net_financing)
            },
            'net_increase': float(net_operating + net_investing + net_financing)
        }

    @classmethod
    def general_ledger(cls, tenant, account_code, start_date, end_date):
        """
        Generate General Ledger for specific account.
        """
        try:
            account = Account.objects.get(tenant=tenant, code=account_code)
        except Account.DoesNotExist:
            return {'error': 'Account not found'}

        # Opening balance
        opening_entries = LedgerEntry.objects.filter(
            tenant=tenant,
            account=account,
            transaction__date__lt=start_date,
            transaction__status='posted'
        )

        opening_debit = opening_entries.aggregate(s=Sum('debit'))['s'] or Decimal('0')
        opening_credit = opening_entries.aggregate(s=Sum('credit'))['s'] or Decimal('0')
        opening_balance = account.opening_balance + opening_debit - opening_credit

        # Period entries
        entries = LedgerEntry.objects.filter(
            tenant=tenant,
            account=account,
            transaction__date__gte=start_date,
            transaction__date__lte=end_date,
            transaction__status='posted'
        ).select_related('transaction').order_by('transaction__date')

        ledger_lines = []
        running_balance = opening_balance

        for entry in entries:
            running_balance += entry.debit - entry.credit

            ledger_lines.append({
                'date': str(entry.transaction.date),
                'reference': entry.transaction.reference_number,
                'narration': entry.transaction.narration,
                'debit': float(entry.debit),
                'credit': float(entry.credit),
                'balance': float(running_balance),
                'description': entry.description
            })

        return {
            'report_type': 'general_ledger',
            'account_code': account.code,
            'account_name': account.name,
            'account_type': account.type,
            'start_date': str(start_date),
            'end_date': str(end_date),
            'opening_balance': float(opening_balance),
            'entries': ledger_lines,
            'closing_balance': float(running_balance),
            'total_debit': sum(e['debit'] for e in ledger_lines),
            'total_credit': sum(e['credit'] for e in ledger_lines)
        }


class OperationalReportService:
    """Operational and business reports."""

    @staticmethod
    def receivables_aging(tenant, as_of_date=None):
        """Accounts Receivable aging report."""
        if as_of_date is None:
            as_of_date = timezone.now().date()

        from apps.invoicing.models import Invoice

        invoices = Invoice.objects.filter(
            tenant=tenant,
            status__in=['sent', 'partial', 'overdue'],
            amount_due__gt=0
        )

        buckets = {
            'current': Decimal('0'),
            '1_30': Decimal('0'),
            '31_60': Decimal('0'),
            '61_90': Decimal('0'),
            '90_plus': Decimal('0')
        }

        customer_breakdown = defaultdict(lambda: {
            'current': Decimal('0'),
            '1_30': Decimal('0'),
            '31_60': Decimal('0'),
            '61_90': Decimal('0'),
            '90_plus': Decimal('0'),
            'total': Decimal('0')
        })

        for inv in invoices:
            days_overdue = (as_of_date - inv.due_date).days

            if days_overdue <= 0:
                bucket = 'current'
            elif days_overdue <= 30:
                bucket = '1_30'
            elif days_overdue <= 60:
                bucket = '31_60'
            elif days_overdue <= 90:
                bucket = '61_90'
            else:
                bucket = '90_plus'

            amount = inv.amount_due
            buckets[bucket] += amount

            customer_name = inv.customer.name if inv.customer else inv.billed_name
            customer_breakdown[customer_name][bucket] += amount
            customer_breakdown[customer_name]['total'] += amount

        return {
            'report_type': 'receivables_aging',
            'as_of_date': str(as_of_date),
            'summary': {k: float(v) for k, v in buckets.items()},
            'total': float(sum(buckets.values())),
            'customers': [
                {
                    'name': name,
                    **{k: float(v) for k, v in data.items()}
                }
                for name, data in sorted(customer_breakdown.items(), key=lambda x: x[1]['total'], reverse=True)
            ]
        }

    @staticmethod
    def payables_aging(tenant, as_of_date=None):
        """Accounts Payable aging report."""
        if as_of_date is None:
            as_of_date = timezone.now().date()

        from apps.purchases.models import SupplierBill

        bills = SupplierBill.objects.filter(
            tenant=tenant,
            status__in=['confirmed', 'partial'],
            amount_due__gt=0
        )

        buckets = {
            'current': Decimal('0'),
            '1_30': Decimal('0'),
            '31_60': Decimal('0'),
            '61_90': Decimal('0'),
            '90_plus': Decimal('0')
        }

        supplier_breakdown = defaultdict(lambda: {
            'current': Decimal('0'),
            '1_30': Decimal('0'),
            '31_60': Decimal('0'),
            '61_90': Decimal('0'),
            '90_plus': Decimal('0'),
            'total': Decimal('0')
        })

        for bill in bills:
            days_overdue = (as_of_date - bill.due_date).days

            if days_overdue <= 0:
                bucket = 'current'
            elif days_overdue <= 30:
                bucket = '1_30'
            elif days_overdue <= 60:
                bucket = '31_60'
            elif days_overdue <= 90:
                bucket = '61_90'
            else:
                bucket = '90_plus'

            amount = bill.amount_due
            buckets[bucket] += amount

            supplier_name = bill.supplier.name
            supplier_breakdown[supplier_name][bucket] += amount
            supplier_breakdown[supplier_name]['total'] += amount

        return {
            'report_type': 'payables_aging',
            'as_of_date': str(as_of_date),
            'summary': {k: float(v) for k, v in buckets.items()},
            'total': float(sum(buckets.values())),
            'suppliers': [
                {
                    'name': name,
                    **{k: float(v) for k, v in data.items()}
                }
                for name, data in sorted(supplier_breakdown.items(), key=lambda x: x[1]['total'], reverse=True)
            ]
        }

    @staticmethod
    def sales_report(tenant, start_date, end_date, group_by='day'):
        """Sales analysis report."""
        invoices = Invoice.objects.filter(
            tenant=tenant,
            invoice_date__gte=start_date,
            invoice_date__lte=end_date,
            status__in=['sent', 'partial', 'paid']
        )

        if group_by == 'day':
            date_format = '%Y-%m-%d'
        elif group_by == 'month':
            date_format = '%Y-%m'
        else:
            date_format = '%Y-%m-%d'

        data = defaultdict(lambda: {
            'count': 0,
            'subtotal': Decimal('0'),
            'vat': Decimal('0'),
            'total': Decimal('0')
        })

        for inv in invoices:
            key = inv.invoice_date.strftime(date_format)
            data[key]['count'] += 1
            data[key]['subtotal'] += inv.subtotal
            data[key]['vat'] += inv.vat_amount
            data[key]['total'] += inv.total_amount

        return {
            'report_type': 'sales_report',
            'start_date': str(start_date),
            'end_date': str(end_date),
            'group_by': group_by,
            'data': [
                {
                    'period': period,
                    'invoice_count': d['count'],
                    'subtotal': float(d['subtotal']),
                    'vat': float(d['vat']),
                    'total': float(d['total'])
                }
                for period, d in sorted(data.items())
            ],
            'totals': {
                'count': sum(d['count'] for d in data.values()),
                'subtotal': float(sum(d['subtotal'] for d in data.values())),
                'vat': float(sum(d['vat'] for d in data.values())),
                'total': float(sum(d['total'] for d in data.values()))
            }
        }

    @staticmethod
    def inventory_report(tenant, as_of_date=None):
        """Inventory valuation and movement report."""
        if as_of_date is None:
            as_of_date = timezone.now().date()

        items = InventoryItem.objects.filter(
            tenant=tenant,
            track_inventory=True
        )

        report_data = []
        total_value = Decimal('0')

        for item in items:
            stock_value = item.get_stock_value()
            total_value += stock_value

            # Get movements in last 30 days
            recent_movements = StockMovement.objects.filter(
                tenant=tenant,
                item=item,
                date__gte=as_of_date - timedelta(days=30)
            ).aggregate(
                in_qty=Sum('quantity', filter=Q(quantity__gt=0)),
                out_qty=Sum('quantity', filter=Q(quantity__lt=0))
            )

            report_data.append({
                'code': item.code,
                'name': item.name,
                'category': item.category,
                'quantity': float(item.stock_quantity),
                'unit_cost': float(item.get_unit_cost()),
                'stock_value': float(stock_value),
                'reorder_level': float(item.reorder_level),
                'is_low_stock': item.is_low_stock(),
                'recent_in': float(recent_movements['in_qty'] or 0),
                'recent_out': float(abs(recent_movements['out_qty'] or 0))
            })

        return {
            'report_type': 'inventory_report',
            'as_of_date': str(as_of_date),
            'items': report_data,
            'total_value': float(total_value),
            'low_stock_count': sum(1 for i in report_data if i['is_low_stock'])
        }