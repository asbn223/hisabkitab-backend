# apps/accounts/serializers.py
"""
Serializers for accounting API.
"""
from decimal import Decimal
from rest_framework import serializers

from .models import Account, Transaction, LedgerEntry, FiscalYear
from core.decimal.decimal_config import calc_line_total, sum_lines, validate_double_entry


class AccountListSerializer(serializers.ModelSerializer):
    """Minimal account info for lists."""

    balance_type = serializers.CharField(source='get_balance_type', read_only=True)
    current_balance = serializers.SerializerMethodField()
    has_children = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = [
            'id', 'code', 'name', 'name_nepali', 'type',
            'balance_type', 'opening_balance', 'current_balance',
            'is_system', 'is_active', 'has_children'
        ]

    def get_current_balance(self, obj):
        """Calculate current balance."""
        balance = obj.get_current_balance()
        return str(balance)

    def get_has_children(self, obj):
        """Check if account has children."""
        return obj.children.filter(is_active=True).exists()


class AccountDetailSerializer(serializers.ModelSerializer):
    """Full account details."""

    parent_code = serializers.CharField(source='parent.code', read_only=True)
    parent_name = serializers.CharField(source='parent.name', read_only=True)
    children = AccountListSerializer(many=True, read_only=True)
    current_balance = serializers.SerializerMethodField()

    class Meta:
        model = Account
        fields = [
            'id', 'code', 'name', 'name_nepali', 'type',
            'parent', 'parent_code', 'parent_name', 'children',
            'description', 'opening_balance', 'current_balance',
            'bank_name', 'bank_account_number',
            'is_system', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'is_system']

    def get_current_balance(self, obj):
        return str(obj.get_current_balance())

    def validate_code(self, value):
        """Ensure code is numeric and valid."""
        if not value.isdigit():
            raise serializers.ValidationError('Account code must be numeric.')
        return value

    def validate(self, data):
        """Prevent circular parent references."""
        if 'parent' in data and data.get('parent'):
            # Can't set self as parent (on update)
            if self.instance and data['parent'].id == self.instance.id:
                raise serializers.ValidationError('Account cannot be its own parent.')
        return data


class LedgerEntrySerializer(serializers.ModelSerializer):
    """Serializer for ledger entries."""

    account_code = serializers.CharField(source='account.code', read_only=True)
    account_name = serializers.CharField(source='account.name', read_only=True)
    account_type = serializers.CharField(source='account.type', read_only=True)
    side = serializers.CharField(source='get_side', read_only=True)
    amount = serializers.CharField(source='get_amount', read_only=True)

    class Meta:
        model = LedgerEntry
        fields = [
            'id', 'account', 'account_code', 'account_name', 'account_type',
            'debit', 'credit', 'side', 'amount', 'description'
        ]

    def validate(self, data):
        """Validate entry has either debit or credit, not both."""
        debit = data.get('debit', Decimal('0'))
        credit = data.get('credit', Decimal('0'))

        if debit > 0 and credit > 0:
            raise serializers.ValidationError(
                'Entry cannot have both debit and credit.'
            )

        if debit == 0 and credit == 0:
            raise serializers.ValidationError(
                'Entry must have either debit or credit.'
            )

        if debit < 0 or credit < 0:
            raise serializers.ValidationError(
                'Amounts cannot be negative.'
            )

        return data


class TransactionListSerializer(serializers.ModelSerializer):
    """Minimal transaction info."""

    entry_count = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'reference_number', 'date', 'bs_date',
            'narration', 'status', 'total_debit', 'total_credit',
            'entry_count', 'created_at'
        ]

    def get_entry_count(self, obj):
        return obj.entries.count()


class TransactionDetailSerializer(serializers.ModelSerializer):
    """Full transaction with entries."""

    entries = LedgerEntrySerializer(many=True)
    is_balanced = serializers.BooleanField(source='is_balanced', read_only=True)
    can_post = serializers.BooleanField(source='can_post', read_only=True)

    class Meta:
        model = Transaction
        fields = [
            'id', 'reference_number', 'date', 'bs_date',
            'narration', 'status', 'is_vat_applicable', 'vat_amount',
            'total_debit', 'total_credit', 'entries',
            'is_balanced', 'can_post',
            'source_type', 'source_id',
            'created_by', 'posted_at', 'posted_by',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'total_debit', 'total_credit', 'status',
            'posted_at', 'posted_by', 'created_at', 'updated_at'
        ]

    def validate_entries(self, entries):
        """Validate that entries balance."""
        if not entries:
            raise serializers.ValidationError('Transaction must have at least one entry.')

        total_debit = sum(
            Decimal(str(e.get('debit', 0))) for e in entries
        )
        total_credit = sum(
            Decimal(str(e.get('credit', 0))) for e in entries
        )

        if not validate_double_entry(total_debit, total_credit):
            raise serializers.ValidationError(
                f'Debits ({total_debit}) must equal Credits ({total_credit}).'
            )

        return entries

    def create(self, validated_data):
        """Create transaction with entries."""
        entries_data = validated_data.pop('entries')

        # Auto-generate reference if not provided
        if not validated_data.get('reference_number'):
            from core.sequence import next_sequence
            validated_data['reference_number'] = next_sequence(
                'JV',
                self.context['request'].tenant.id
            )

        # Set BS date if not provided
        if not validated_data.get('bs_date'):
            from core.bs_date import ad_to_bs
            validated_data['bs_date'] = ad_to_bs(
                str(validated_data['date'])
            )

        transaction = Transaction.objects.create(**validated_data)

        # Create entries
        for entry_data in entries_data:
            LedgerEntry.objects.create(
                transaction=transaction,
                tenant=transaction.tenant,
                **entry_data
            )

        return transaction

    def update(self, instance, validated_data):
        """Update draft transaction."""
        if not instance.can_edit():
            raise serializers.ValidationError(
                'Only draft transactions can be edited.'
            )

        entries_data = validated_data.pop('entries', None)

        # Update transaction fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Replace entries if provided
        if entries_data:
            # Validate balance
            total_debit = sum(Decimal(str(e.get('debit', 0))) for e in entries_data)
            total_credit = sum(Decimal(str(e.get('credit', 0))) for e in entries_data)

            if not validate_double_entry(total_debit, total_credit):
                raise serializers.ValidationError('Entries do not balance.')

            # Delete old entries
            instance.entries.all().delete()

            # Create new entries
            for entry_data in entries_data:
                LedgerEntry.objects.create(
                    transaction=instance,
                    tenant=instance.tenant,
                    **entry_data
                )

        return instance


class LedgerReportSerializer(serializers.Serializer):
    """Serializer for ledger report output."""

    account_id = serializers.IntegerField()
    account_code = serializers.CharField()
    account_name = serializers.CharField()
    account_type = serializers.CharField()
    opening_balance = serializers.CharField()
    entries = LedgerEntrySerializer(many=True)
    closing_balance = serializers.CharField()
    total_debit = serializers.CharField()
    total_credit = serializers.CharField()


class TrialBalanceSerializer(serializers.Serializer):
    """Serializer for trial balance report."""

    as_of = serializers.DateField()
    accounts = serializers.ListField(
        child=serializers.DictField()
    )
    total_debit = serializers.CharField()
    total_credit = serializers.CharField()


class FiscalYearSerializer(serializers.ModelSerializer):
    """Serializer for fiscal years."""

    is_current = serializers.BooleanField(source='is_current', read_only=True)

    class Meta:
        model = FiscalYear
        fields = [
            'id', 'year_name', 'start_date', 'end_date',
            'is_closed', 'is_current',
            'retained_earnings_account',
            'created_at'
        ]
        read_only_fields = ['created_at']