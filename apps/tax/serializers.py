from rest_framework import serializers
from .models import (
    TaxPeriod, VATReturn, VATTransaction, TDSSection,
    TDSDeduction, TDSReturn, TaxDeposit, TaxCertificate, TaxConfig
)


class TaxConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxConfig
        fields = '__all__'
        read_only_fields = ['tenant']


class TaxPeriodSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    period_type_display = serializers.CharField(source='get_period_type_display', read_only=True)

    class Meta:
        model = TaxPeriod
        fields = [
            'id', 'period_type', 'period_type_display', 'year_month',
            'fiscal_year', 'start_date', 'end_date', 'due_date',
            'status', 'status_display', 'total_sales_vat',
            'total_purchase_vat', 'vat_payable', 'ird_submitted',
            'created_at'
        ]


class VATReturnSerializer(serializers.ModelSerializer):
    return_type_display = serializers.CharField(source='get_return_type_display', read_only=True)

    class Meta:
        model = VATReturn
        fields = [
            'id', 'return_type', 'return_type_display', 'return_number',
            'tax_period', 'local_taxable_sales', 'local_vat_amount',
            'local_exempt_sales', 'export_zero_rated', 'export_taxable',
            'local_taxable_purchases', 'local_vat_paid', 'import_vat',
            'vat_output', 'vat_input', 'vat_credit_brought_forward',
            'vat_credit_carried_forward', 'net_vat_payable',
            'is_finalized', 'finalized_at', 'ird_reference'
        ]


class VATTransactionSerializer(serializers.ModelSerializer):
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    vat_type_display = serializers.CharField(source='get_vat_type_display', read_only=True)

    class Meta:
        model = VATTransaction
        fields = [
            'id', 'transaction_type', 'transaction_type_display',
            'source_number', 'source_date', 'party_name', 'party_pan',
            'vat_type', 'vat_type_display', 'vat_rate', 'taxable_amount',
            'vat_amount', 'total_amount', 'is_ird_synced', 'is_reconciled'
        ]


class TDSSectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TDSSection
        fields = ['id', 'section_code', 'description', 'rate_percent', 'threshold_amount', 'is_active']


class TDSDeductionSerializer(serializers.ModelSerializer):
    section_code = serializers.CharField(source='tds_section.section_code', read_only=True)
    deduction_type_display = serializers.CharField(source='get_deduction_type_display', read_only=True)

    class Meta:
        model = TDSDeduction
        fields = [
            'id', 'tds_section', 'section_code', 'deduction_type',
            'deduction_type_display', 'document_number', 'date',
            'party_name', 'party_pan', 'base_amount', 'tds_rate',
            'tds_amount', 'net_amount', 'is_deposited', 'deposited_date'
        ]


class TDSReturnSerializer(serializers.ModelSerializer):
    return_type_display = serializers.CharField(source='get_return_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = TDSReturn
        fields = [
            'id', 'return_type', 'return_type_display', 'return_number',
            'tax_period', 'total_deducted', 'total_deposit',
            'interest_penalty', 'total_payable', 'status', 'status_display',
            'filed_at', 'ird_acknowledgement'
        ]


class TaxDepositSerializer(serializers.ModelSerializer):
    tax_type_display = serializers.CharField(source='get_tax_type_display', read_only=True)
    payment_mode_display = serializers.CharField(source='get_payment_mode_display', read_only=True)

    class Meta:
        model = TaxDeposit
        fields = [
            'id', 'deposit_number', 'tax_type', 'tax_type_display',
            'principal_amount', 'interest_amount', 'penalty_amount',
            'total_amount', 'date', 'payment_mode', 'payment_mode_display',
            'bank_voucher_no', 'ird_reference', 'notes'
        ]


class TaxCertificateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxCertificate
        fields = [
            'id', 'certificate_number', 'party_name', 'party_pan',
            'amount_paid', 'tax_deducted', 'issue_date', 'is_downloaded'
        ]