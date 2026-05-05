# apps/accounts/views.py
"""
API views for accounting operations.
"""
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import Account, Transaction, LedgerEntry, FiscalYear
from .serializers import (
    AccountListSerializer, AccountDetailSerializer,
    TransactionListSerializer, TransactionDetailSerializer,
    LedgerEntrySerializer, FiscalYearSerializer
)
from .services import (
    post_transaction, cancel_transaction,
    get_account_ledger, get_trial_balance,
    close_fiscal_year
)
from core.db.locks import serializable_transaction
from core.exceptions import (
    DoubleEntryError, ImmutableEntityError, FiscalYearClosedError
)
from apps.tenants.permissions import (
    TenantPermission, IsAccountant, CanPostTransactions
)


class AccountViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Chart of Accounts management.
    """
    permission_classes = [IsAuthenticated, TenantPermission]

    def get_queryset(self):
        """Filter by tenant and active status."""
        return Account.objects.filter(
            tenant=self.request.tenant,
            is_active=True
        ).select_related('parent').prefetch_related('children')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return AccountDetailSerializer
        return AccountListSerializer

    def perform_create(self, serializer):
        """Set tenant on creation."""
        serializer.save(tenant=self.request.tenant)

    def perform_destroy(self, instance):
        """Soft delete (deactivate) instead of hard delete."""
        if instance.is_system:
            return Response(
                {'error': 'System accounts cannot be deleted.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check for ledger entries
        if LedgerEntry.objects.filter(account=instance).exists():
            return Response(
                {'error': 'Account with transactions cannot be deleted. Deactivate instead.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        instance.is_active = False
        instance.save()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'])
    def ledger(self, request, pk=None):
        """Get ledger entries for this account."""
        account = self.get_object()

        from_date = request.query_params.get('from')
        to_date = request.query_params.get('to')

        data = get_account_ledger(
            account,
            from_date=from_date,
            to_date=to_date
        )

        return Response(data)

    @action(detail=False, methods=['get'])
    def balance_sheet(self, request):
        """Get balance sheet report."""
        as_of = request.query_params.get('as_of')

        accounts = Account.objects.filter(
            tenant=request.tenant,
            is_active=True
        )

        assets = []
        liabilities = []
        equity = []

        total_assets = Decimal('0')
        total_liabilities = Decimal('0')
        total_equity = Decimal('0')

        for account in accounts:
            balance = account.get_current_balance(as_of)

            if account.type == 'asset' and balance != 0:
                assets.append({
                    'code': account.code,
                    'name': account.name,
                    'balance': str(abs(balance))
                })
                total_assets += abs(balance)

            elif account.type == 'liability' and balance != 0:
                liabilities.append({
                    'code': account.code,
                    'name': account.name,
                    'balance': str(abs(balance))
                })
                total_liabilities += abs(balance)

            elif account.type == 'equity' and balance != 0:
                equity.append({
                    'code': account.code,
                    'name': account.name,
                    'balance': str(abs(balance))
                })
                total_equity += abs(balance)

        # Add net income to equity
        income_balance = Decimal('0')
        expense_balance = Decimal('0')

        for account in accounts.filter(type__in=['income', 'expense']):
            balance = account.get_current_balance(as_of)
            if account.type == 'income':
                income_balance += balance
            else:
                expense_balance += balance

        net_income = income_balance - expense_balance
        if net_income != 0:
            equity.append({
                'code': 'NET',
                'name': 'Current Year Net Income',
                'balance': str(abs(net_income))
            })
            total_equity += abs(net_income)

        return Response({
            'as_of': as_of or timezone.now().date(),
            'assets': assets,
            'total_assets': str(total_assets),
            'liabilities': liabilities,
            'total_liabilities': str(total_liabilities),
            'equity': equity,
            'total_equity': str(total_equity),
            'liabilities_plus_equity': str(total_liabilities + total_equity)
        })

    @action(detail=False, methods=['get'])
    def profit_loss(self, request):
        """Get profit and loss report."""
        from_date = request.query_params.get('from')
        to_date = request.query_params.get('to')

        accounts = Account.objects.filter(
            tenant=request.tenant,
            is_active=True,
            type__in=['income', 'expense']
        )

        income = []
        expenses = []

        total_income = Decimal('0')
        total_expenses = Decimal('0')

        for account in accounts:
            # For income/expense, we want period totals, not balance
            entries = LedgerEntry.objects.filter(
                tenant=request.tenant,
                account=account,
                transaction__status='posted'
            )

            if from_date:
                entries = entries.filter(transaction__date__gte=from_date)
            if to_date:
                entries = entries.filter(transaction__date__lte=to_date)

            sums = entries.aggregate(
                debit=Sum('debit'),
                credit=Sum('credit')
            )

            debit = sums['debit'] or Decimal('0')
            credit = sums['credit'] or Decimal('0')

            # Income: Credit increases (normal balance)
            # Expense: Debit increases (normal balance)
            if account.type == 'income':
                amount = credit - debit
                if amount != 0:
                    income.append({
                        'code': account.code,
                        'name': account.name,
                        'amount': str(abs(amount))
                    })
                    total_income += abs(amount)
            else:
                amount = debit - credit
                if amount != 0:
                    expenses.append({
                        'code': account.code,
                        'name': account.name,
                        'amount': str(abs(amount))
                    })
                    total_expenses += abs(amount)

        net_profit = total_income - total_expenses

        return Response({
            'from_date': from_date,
            'to_date': to_date,
            'income': income,
            'total_income': str(total_income),
            'expenses': expenses,
            'total_expenses': str(total_expenses),
            'net_profit': str(net_profit),
            'is_profit': net_profit >= 0
        })


class TransactionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for journal voucher transactions.
    """
    permission_classes = [IsAuthenticated, TenantPermission]

    def get_queryset(self):
        """Filter by tenant."""
        queryset = Transaction.objects.filter(
            tenant=self.request.tenant
        ).prefetch_related('entries', 'entries__account')

        # Filters
        status = self.request.query_params.get('status')
        from_date = self.request.query_params.get('from')
        to_date = self.request.query_params.get('to')
        account_id = self.request.query_params.get('account_id')

        if status:
            queryset = queryset.filter(status=status)
        if from_date:
            queryset = queryset.filter(date__gte=from_date)
        if to_date:
            queryset = queryset.filter(date__lte=to_date)
        if account_id:
            queryset = queryset.filter(entries__account_id=account_id).distinct()

        return queryset.order_by('-date', '-created_at')

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return TransactionDetailSerializer
        return TransactionListSerializer

    def perform_create(self, serializer):
        """Set tenant and created_by."""
        serializer.save(
            tenant=self.request.tenant,
            created_by=str(self.request.user.id)
        )

    @action(detail=True, methods=['post'], permission_classes=[CanPostTransactions])
    def post(self, request, pk=None):
        """Post a transaction with SERIALIZABLE isolation."""
        txn = self.get_object()

        try:
            with serializable_transaction():
                posted_txn = post_transaction(
                    txn.id,
                    posted_by=str(request.user.id)
                )

                serializer = TransactionDetailSerializer(posted_txn)
                return Response(serializer.data)

        except DoubleEntryError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except ImmutableEntityError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_409_CONFLICT
            )

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel a draft transaction."""
        txn = self.get_object()
        reason = request.data.get('reason', '')

        try:
            cancelled_txn = cancel_transaction(
                txn.id,
                cancelled_by=str(request.user.id),
                reason=reason
            )

            serializer = TransactionDetailSerializer(cancelled_txn)
            return Response(serializer.data)

        except ImmutableEntityError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['get'])
    def trial_balance(self, request):
        """Generate trial balance report."""
        as_of = request.query_params.get('as_of')

        data = get_trial_balance(request.tenant, as_of)
        return Response(data)


class LedgerViewSet(viewsets.ViewSet):
    """
    Read-only ledger view.
    """
    permission_classes = [IsAuthenticated, TenantPermission]

    def list(self, request):
        """Get ledger entries with filtering."""
        account_id = request.query_params.get('account_id')
        if not account_id:
            return Response(
                {'error': 'account_id parameter required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            account = Account.objects.get(
                id=account_id,
                tenant=request.tenant
            )
        except Account.DoesNotExist:
            return Response(
                {'error': 'Account not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        from_date = request.query_params.get('from')
        to_date = request.query_params.get('to')

        data = get_account_ledger(account, from_date, to_date)
        return Response(data)


class FiscalYearViewSet(viewsets.ModelViewSet):
    """
    ViewSet for fiscal year management.
    """
    serializer_class = FiscalYearSerializer
    permission_classes = [IsAuthenticated, TenantPermission, IsAccountant]

    def get_queryset(self):
        return FiscalYear.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        """Set tenant."""
        serializer.save(tenant=self.request.tenant)

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """Close fiscal year."""
        fy = self.get_object()

        if fy.is_closed:
            return Response(
                {'error': 'Fiscal year is already closed'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            result = close_fiscal_year(
                fy.id,
                closed_by=str(request.user.id)
            )
            return Response(result)
        except FiscalYearClosedError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )