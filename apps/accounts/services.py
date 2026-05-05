# apps/accounts/services.py
"""
Business logic for accounting operations.
"""
from decimal import Decimal
from typing import Optional, List, Dict

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Account, Transaction, LedgerEntry, FiscalYear
from core.db.locks import serializable_transaction, advisory_lock
from core.decimal.decimal_config import fiscal_round, validate_double_entry
from core.exceptions import (
    DoubleEntryError, ImmutableEntityError, FiscalYearClosedError
)
from core.bs_date import get_current_bs_date


def seed_chart_of_accounts(tenant) -> None:
    """
    Create default Nepali chart of accounts for new tenant.

    Based on DH-To-An-Ka (Debit-Credit) system used in Nepal.
    """
    accounts = [
        # ASSETS (1xxxxx) - Debit increases
        {'code': '10101', 'name': 'Cash in Hand', 'type': 'asset', 'is_system': True},
        {'code': '10102', 'name': 'Bank Accounts', 'type': 'asset', 'is_system': True},
        {'code': '10103', 'name': 'eSewa Wallet', 'type': 'asset', 'is_system': True},
        {'code': '10104', 'name': 'Khalti Wallet', 'type': 'asset', 'is_system': True},
        {'code': '10105', 'name': 'Fonepay Wallet', 'type': 'asset', 'is_system': True},
        {'code': '10201', 'name': 'Accounts Receivable', 'type': 'asset', 'is_system': True},
        {'code': '10202', 'name': 'Allowance for Doubtful Accounts', 'type': 'asset', 'is_system': True},
        {'code': '10301', 'name': 'Inventory - Raw Materials', 'type': 'asset', 'is_system': True},
        {'code': '10302', 'name': 'Inventory - Finished Goods', 'type': 'asset', 'is_system': True},
        {'code': '10401', 'name': 'Prepaid Expenses', 'type': 'asset', 'is_system': False},
        {'code': '10501', 'name': 'Furniture & Fixtures', 'type': 'asset', 'is_system': True},
        {'code': '10502', 'name': 'Computer Equipment', 'type': 'asset', 'is_system': False},
        {'code': '10503', 'name': 'Vehicles', 'type': 'asset', 'is_system': False},
        {'code': '10601', 'name': 'Accumulated Depreciation', 'type': 'asset', 'is_system': True},

        # LIABILITIES (2xxxxx) - Credit increases
        {'code': '20101', 'name': 'VAT Output (Sales)', 'type': 'liability', 'is_system': True},
        {'code': '20102', 'name': 'VAT Input (Purchase)', 'type': 'liability', 'is_system': True},
        {'code': '20103', 'name': 'VAT Payable', 'type': 'liability', 'is_system': True},
        {'code': '20201', 'name': 'Accounts Payable', 'type': 'liability', 'is_system': True},
        {'code': '20301', 'name': 'Short-term Loans', 'type': 'liability', 'is_system': False},
        {'code': '20302', 'name': 'Long-term Loans', 'type': 'liability', 'is_system': False},
        {'code': '20401', 'name': 'Salaries Payable', 'type': 'liability', 'is_system': False},
        {'code': '20402', 'name': 'Taxes Payable', 'type': 'liability', 'is_system': True},

        # EQUITY (3xxxxx) - Credit increases
        {'code': '30101', 'name': 'Owner Capital', 'type': 'equity', 'is_system': True},
        {'code': '30102', 'name': 'Partner Capital', 'type': 'equity', 'is_system': False},
        {'code': '30201', 'name': 'Retained Earnings', 'type': 'equity', 'is_system': True},
        {'code': '30301', 'name': 'Owner Drawings', 'type': 'equity', 'is_system': True},

        # INCOME (4xxxxx) - Credit increases
        {'code': '40101', 'name': 'Sales Revenue', 'type': 'income', 'is_system': True},
        {'code': '40102', 'name': 'Service Revenue', 'type': 'income', 'is_system': True},
        {'code': '40201', 'name': 'Interest Income', 'type': 'income', 'is_system': False},
        {'code': '40202', 'name': 'Other Income', 'type': 'income', 'is_system': False},
        {'code': '40301', 'name': 'Sales Returns & Allowances', 'type': 'income', 'is_system': True},
        {'code': '40302', 'name': 'Sales Discounts', 'type': 'income', 'is_system': True},

        # EXPENSES (5xxxxx) - Debit increases
        {'code': '50101', 'name': 'Cost of Goods Sold', 'type': 'expense', 'is_system': True},
        {'code': '50201', 'name': 'Rent Expense', 'type': 'expense', 'is_system': True},
        {'code': '50202', 'name': 'Salary Expense', 'type': 'expense', 'is_system': True},
        {'code': '50203', 'name': 'Utilities Expense', 'type': 'expense', 'is_system': True},
        {'code': '50204', 'name': 'Office Supplies', 'type': 'expense', 'is_system': False},
        {'code': '50301', 'name': 'Depreciation Expense', 'type': 'expense', 'is_system': True},
        {'code': '50401', 'name': 'Interest Expense', 'type': 'expense', 'is_system': False},
        {'code': '50501', 'name': 'Bank Charges', 'type': 'expense', 'is_system': True},
        {'code': '50601', 'name': 'Bad Debt Expense', 'type': 'expense', 'is_system': False},
    ]

    for acc_data in accounts:
        Account.objects.get_or_create(
            tenant=tenant,
            code=acc_data['code'],
            defaults={
                'name': acc_data['name'],
                'type': acc_data['type'],
                'is_system': acc_data['is_system'],
                'opening_balance': Decimal('0.0000'),
            }
        )


def post_transaction(transaction_id: int, posted_by: str) -> Transaction:
    """
    Post a transaction with SERIALIZABLE isolation.

    Args:
        transaction_id: Transaction to post
        posted_by: User ID posting the transaction

    Returns:
        Posted Transaction

    Raises:
        DoubleEntryError: If debits don't equal credits
        ImmutableEntityError: If already posted or cancelled
    """
    with serializable_transaction():
        txn = Transaction.objects.select_for_update().get(id=transaction_id)

        if txn.status == 'posted':
            raise ImmutableEntityError('Transaction is already posted')

        if txn.status == 'cancelled':
            raise ImmutableEntityError('Cannot post cancelled transaction')

        # Calculate totals
        entries = txn.entries.all()
        total_debit = sum(e.debit for e in entries)
        total_credit = sum(e.credit for e in entries)

        # Validate balance
        if not validate_double_entry(total_debit, total_credit):
            raise DoubleEntryError(
                f'Debits ({total_debit}) do not equal Credits ({total_credit})'
            )

        # Update transaction
        txn.status = 'posted'
        txn.total_debit = fiscal_round(total_debit, 4)
        txn.total_credit = fiscal_round(total_credit, 4)
        txn.posted_at = timezone.now()
        txn.posted_by = posted_by
        txn.save()

        # Create audit log
        from apps.audit.models import AuditLog
        AuditLog.objects.create(
            tenant=txn.tenant,
            entity_type='transaction',
            entity_id=txn.id,
            action='posted',
            changed_by=posted_by,
            new_data={
                'status': 'posted',
                'total_debit': str(txn.total_debit),
                'total_credit': str(txn.total_credit),
            }
        )

        return txn


def cancel_transaction(transaction_id: int, cancelled_by: str,
                       reason: str = '') -> Transaction:
    """
    Cancel a draft transaction.

    Args:
        transaction_id: Transaction to cancel
        cancelled_by: User ID cancelling
        reason: Cancellation reason

    Returns:
        Cancelled Transaction

    Raises:
        ImmutableEntityError: If already posted
    """
    txn = Transaction.objects.get(id=transaction_id)

    if txn.status == 'posted':
        raise ImmutableEntityError(
            'Posted transactions cannot be cancelled. Create a reversing entry instead.'
        )

    if txn.status == 'cancelled':
        raise ImmutableEntityError('Transaction is already cancelled')

    txn.status = 'cancelled'
    txn.cancelled_at = timezone.now()
    txn.cancelled_by = cancelled_by
    txn.cancellation_reason = reason
    txn.save()

    # Audit log
    from apps.audit.models import AuditLog
    AuditLog.objects.create(
        tenant=txn.tenant,
        entity_type='transaction',
        entity_id=txn.id,
        action='cancelled',
        changed_by=cancelled_by,
        new_data={
            'status': 'cancelled',
            'reason': reason,
        }
    )

    return txn


def get_account_ledger(account: Account, from_date=None,
                       to_date=None) -> Dict:
    """
    Generate ledger report for an account.

    Returns:
        Dict with opening balance, entries, closing balance
    """
    # Get opening balance (before from_date)
    opening_balance = account.opening_balance

    if from_date:
        prior_entries = LedgerEntry.objects.filter(
            tenant=account.tenant,
            account=account,
            transaction__status='posted',
            transaction__date__lt=from_date
        )

        prior_sums = prior_entries.aggregate(
            debit=Sum('debit'),
            credit=Sum('credit')
        )

        opening_balance += (
                (prior_sums['debit'] or Decimal('0')) -
                (prior_sums['credit'] or Decimal('0'))
        )

    # Get entries in period
    entries_qs = LedgerEntry.objects.filter(
        tenant=account.tenant,
        account=account,
        transaction__status='posted'
    ).select_related('transaction').order_by('transaction__date', 'transaction__id')

    if from_date:
        entries_qs = entries_qs.filter(transaction__date__gte=from_date)
    if to_date:
        entries_qs = entries_qs.filter(transaction__date__lte=to_date)

    # Calculate running balance
    balance = opening_balance
    entries_data = []
    total_debit = Decimal('0')
    total_credit = Decimal('0')

    for entry in entries_qs:
        balance += entry.debit - entry.credit
        total_debit += entry.debit
        total_credit += entry.credit

        entries_data.append({
            'id': entry.id,
            'date': entry.transaction.date,
            'bs_date': entry.transaction.bs_date,
            'reference': entry.transaction.reference_number,
            'narration': entry.description or entry.transaction.narration,
            'debit': str(entry.debit) if entry.debit > 0 else '',
            'credit': str(entry.credit) if entry.credit > 0 else '',
            'balance': str(fiscal_round(balance, 4)),
        })

    return {
        'account_id': account.id,
        'account_code': account.code,
        'account_name': account.name,
        'account_type': account.type,
        'opening_balance': str(fiscal_round(opening_balance, 4)),
        'entries': entries_data,
        'total_debit': str(fiscal_round(total_debit, 4)),
        'total_credit': str(fiscal_round(total_credit, 4)),
        'closing_balance': str(fiscal_round(balance, 4)),
        'period_from': from_date,
        'period_to': to_date,
    }


def get_trial_balance(tenant, as_of=None) -> Dict:
    """
    Generate trial balance report.

    Args:
        tenant: Tenant instance
        as_of: Date string (optional)

    Returns:
        Trial balance data
    """
    accounts = Account.objects.filter(
        tenant=tenant,
        is_active=True
    ).order_by('code')

    entries = []
    total_debit = Decimal('0')
    total_credit = Decimal('0')

    for account in accounts:
        balance = account.get_current_balance(as_of)

        if balance == 0:
            continue

        # Determine debit/credit presentation
        if balance > 0:
            # Positive balance = debit for assets/expenses, credit for others
            if account.type in ('asset', 'expense'):
                debit = balance
                credit = Decimal('0')
            else:
                debit = Decimal('0')
                credit = balance
        else:
            # Negative balance
            if account.type in ('asset', 'expense'):
                debit = Decimal('0')
                credit = abs(balance)
            else:
                debit = abs(balance)
                credit = Decimal('0')

        entries.append({
            'account_id': account.id,
            'account_code': account.code,
            'account_name': account.name,
            'account_type': account.type,
            'debit': str(fiscal_round(debit, 4)),
            'credit': str(fiscal_round(credit, 4)),
        })

        total_debit += debit
        total_credit += credit

    return {
        'as_of': as_of or timezone.now().date(),
        'entries': entries,
        'total_debit': str(fiscal_round(total_debit, 4)),
        'total_credit': str(fiscal_round(total_credit, 4)),
        'is_balanced': fiscal_round(total_debit) == fiscal_round(total_credit),
    }


def create_auto_transaction(
        tenant,
        narration: str,
        entries: List[Dict],
        source_type: str = '',
        source_id: int = None,
        date=None,
        created_by: str = ''
) -> Transaction:
    """
    Create a transaction from automated source (invoice, payment, etc.).

    Args:
        tenant: Tenant instance
        narration: Transaction description
        entries: List of {account_id, debit, credit, description}
        source_type: Source document type
        source_id: Source document ID
        date: Transaction date (default: today)
        created_by: User ID

    Returns:
        Created Transaction
    """
    from core.sequence import next_sequence
    from core.bs_date import ad_to_bs

    if date is None:
        from datetime import date as dt
        date = dt.today()

    # Validate entries balance
    total_debit = sum(Decimal(str(e.get('debit', 0))) for e in entries)
    total_credit = sum(Decimal(str(e.get('credit', 0))) for e in entries)

    if not validate_double_entry(total_debit, total_credit):
        raise DoubleEntryError('Auto-transaction entries do not balance')

    # Create transaction
    txn = Transaction.objects.create(
        tenant=tenant,
        reference_number=next_sequence('AUTO', tenant.id),
        date=date,
        bs_date=ad_to_bs(str(date)),
        narration=narration,
        status='draft',  # Will be posted immediately
        source_type=source_type,
        source_id=source_id,
        created_by=created_by,
    )

    # Create entries
    for entry_data in entries:
        LedgerEntry.objects.create(
            tenant=tenant,
            transaction=txn,
            account_id=entry_data['account_id'],
            debit=Decimal(str(entry_data.get('debit', 0))),
            credit=Decimal(str(entry_data.get('credit', 0))),
            description=entry_data.get('description', ''),
        )

    # Auto-post
    post_transaction(txn.id, created_by or 'system')

    return txn


def close_fiscal_year(fiscal_year_id: int, closed_by: str) -> Dict:
    """
    Close fiscal year and transfer net income to retained earnings.

    Args:
        fiscal_year_id: FiscalYear to close
        closed_by: User ID

    Returns:
        Closing summary
    """
    fy = FiscalYear.objects.select_related('tenant').get(id=fiscal_year_id)

    if fy.is_closed:
        raise FiscalYearClosedError('Fiscal year is already closed')

    # Calculate net income
    accounts = Account.objects.filter(
        tenant=fy.tenant,
        type__in=['income', 'expense'],
        is_active=True
    )

    net_income = Decimal('0')

    for account in accounts:
        balance = account.get_current_balance(fy.end_date)
        if account.type == 'income':
            net_income += balance  # Income is credit balance
        else:
            net_income -= balance  # Expense is debit balance

    # Create closing entry if there's net income/loss
    if net_income != 0:
        retained_earnings = fy.retained_earnings_account or Account.objects.get(
            tenant=fy.tenant,
            code='30201'  # Retained Earnings
        )

        # Determine accounts based on profit/loss
        if net_income > 0:
            # Profit: Credit retained earnings, debit income summary
            closing_entries = [
                {
                    'account_id': Account.objects.get(
                        tenant=fy.tenant,
                        code='40101'  # Sales Revenue proxy
                    ).id,
                    'debit': abs(net_income),
                    'credit': 0,
                    'description': 'Closing entry - Revenue',
                },
                {
                    'account_id': retained_earnings.id,
                    'debit': 0,
                    'credit': abs(net_income),
                    'description': f'Net profit for {fy.year_name}',
                }
            ]
        else:
            # Loss: Debit retained earnings, credit expense summary
            closing_entries = [
                {
                    'account_id': retained_earnings.id,
                    'debit': abs(net_income),
                    'credit': 0,
                    'description': f'Net loss for {fy.year_name}',
                },
                {
                    'account_id': Account.objects.get(
                        tenant=fy.tenant,
                        code='50101'  # COGS proxy
                    ).id,
                    'debit': 0,
                    'credit': abs(net_income),
                    'description': 'Closing entry - Expenses',
                }
            ]

        create_auto_transaction(
            tenant=fy.tenant,
            narration=f'Year-end closing for {fy.year_name}',
            entries=closing_entries,
            source_type='fiscal_year_close',
            source_id=fy.id,
            date=fy.end_date,
            created_by=closed_by,
        )

    # Mark fiscal year closed
    fy.is_closed = True
    fy.closed_at = timezone.now()
    fy.closed_by = closed_by
    fy.save()

    return {
        'fiscal_year': fy.year_name,
        'net_income': str(net_income),
        'is_profit': net_income > 0,
        'closed_at': fy.closed_at.isoformat(),
    }