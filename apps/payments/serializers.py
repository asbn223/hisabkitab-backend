from rest_framework import serializers
from .models import PaymentGateway, PaymentTransaction, PaymentRefund, BankAccount, BankStatement, BankStatementLine


class PaymentGatewaySerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentGateway
        fields = [
            'id', 'gateway_type', 'name', 'is_active', 'environment',
            'merchant_id', 'service_charge_percent', 'min_amount', 'max_amount',
            'settlement_account', 'fee_expense_account', 'created_at'
        ]
        extra_kwargs = {
            'merchant_key': {'write_only': True},
            'api_secret': {'write_only': True},
        }


class PaymentTransactionSerializer(serializers.ModelSerializer):
    gateway_name = serializers.CharField(source='gateway.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    method_display = serializers.CharField(source='get_payment_method_display', read_only=True)

    class Meta:
        model = PaymentTransaction
        fields = [
            'id', 'transaction_id', 'gateway', 'gateway_name',
            'direction', 'status', 'status_display',
            'payment_method', 'method_display',
            'amount', 'currency', 'gateway_fee', 'net_amount',
            'customer_name', 'customer_email', 'customer_phone',
            'source_type', 'source_id', 'source_number',
            'gateway_transaction_id', 'gateway_response_message',
            'initiated_at', 'completed_at', 'is_reconciled',
            'description'
        ]
        read_only_fields = ['transaction_id', 'net_amount']


class PaymentRefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentRefund
        fields = '__all__'


class BankAccountSerializer(serializers.ModelSerializer):
    current_balance = serializers.DecimalField(
        max_digits=15,
        decimal_places=4,
        read_only=True
    )

    class Meta:
        model = BankAccount
        fields = [
            'id', 'account_name', 'bank_name', 'branch',
            'account_number', 'account_type', 'currency',
            'opening_balance', 'current_balance',
            'ledger_account', 'statement_format',
            'is_active', 'is_default', 'created_at'
        ]


class BankStatementLineSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = BankStatementLine
        fields = [
            'id', 'date', 'bs_date', 'description', 'reference',
            'debit', 'credit', 'amount', 'running_balance',
            'status', 'status_display', 'match_suggestions',
            'matched_transaction', 'matched_invoice', 'matched_bill',
            'notes'
        ]


class BankStatementSerializer(serializers.ModelSerializer):
    lines = BankStatementLineSerializer(many=True, read_only=True)
    account_name = serializers.CharField(source='account.account_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = BankStatement
        fields = [
            'id', 'account', 'account_name', 'statement_date',
            'start_date', 'end_date', 'status', 'status_display',
            'opening_balance', 'closing_balance',
            'total_debits', 'total_credits', 'lines',
            'created_at'
        ]