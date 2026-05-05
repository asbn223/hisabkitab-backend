"""
Payment processing services.
"""
from decimal import Decimal
from django.utils import timezone

from .models import PaymentTransaction, PaymentGateway, BankStatementLine
from .gateways.esewa import EsewaGateway
from .gateways.khalti import KhaltiGateway
from .gateways.connectips import ConnectIPSGateway


class PaymentService:
    """Main service for payment operations."""

    GATEWAY_MAP = {
        'esewa': EsewaGateway,
        'khalti': KhaltiGateway,
        'connectips': ConnectIPSGateway,
    }

    @classmethod
    def initialize_payment(cls, tenant, gateway_type, amount, **kwargs):
        """Initialize a new payment transaction."""

        # Get gateway config
        gateway = PaymentGateway.objects.filter(
            tenant=tenant,
            gateway_type=gateway_type,
            is_active=True
        ).first()

        if not gateway:
            return {
                'success': False,
                'error': f'Gateway {gateway_type} not configured'
            }

        # Validate amount
        if amount < gateway.min_amount or amount > gateway.max_amount:
            return {
                'success': False,
                'error': f'Amount must be between {gateway.min_amount} and {gateway.max_amount}'
            }

        # Create transaction record
        txn = PaymentTransaction.objects.create(
            tenant=tenant,
            gateway=gateway,
            amount=amount,
            currency=kwargs.get('currency', 'NPR'),
            payment_method=gateway_type,
            direction=kwargs.get('direction', 'incoming'),
            customer_name=kwargs.get('customer_name', ''),
            customer_email=kwargs.get('customer_email', ''),
            customer_phone=kwargs.get('customer_phone', ''),
            source_type=kwargs.get('source_type', ''),
            source_id=kwargs.get('source_id'),
            source_number=kwargs.get('source_number', ''),
            description=kwargs.get('description', ''),
            success_url=kwargs.get('success_url', ''),
            failure_url=kwargs.get('failure_url', ''),
            cancel_url=kwargs.get('cancel_url', ''),
            created_by=kwargs.get('user', '')
        )

        # Calculate fees
        txn.gateway_fee = gateway.service_charge_percent / 100 * amount
        txn.net_amount = amount - txn.gateway_fee
        txn.save()

        # Get gateway instance
        gateway_class = cls.GATEWAY_MAP.get(gateway_type)
        if not gateway_class:
            return {
                'success': False,
                'error': 'Gateway implementation not found'
            }

        gateway_instance = gateway_class(gateway)

        # Initialize with gateway
        result = gateway_instance.initialize_payment(
            amount=amount,
            transaction_id=txn.transaction_id,
            description=txn.description,
            customer_name=txn.customer_name,
            customer_email=txn.customer_email,
            customer_phone=txn.customer_phone,
            website_url=kwargs.get('website_url', '')
        )

        if result.get('success'):
            txn.status = 'pending'
            txn.save()

        return {
            'success': True,
            'transaction_id': txn.transaction_id,
            'payment_data': result,
            'amount': amount,
            'fees': txn.gateway_fee,
            'net_amount': txn.net_amount
        }

    @classmethod
    def process_callback(cls, gateway_type, request_data, query_params):
        """Process payment gateway callback."""

        transaction_id = query_params.get('txn') or request_data.get('transaction_uuid')

        try:
            txn = PaymentTransaction.objects.get(transaction_id=transaction_id)
        except PaymentTransaction.DoesNotExist:
            return {'success': False, 'error': 'Transaction not found'}

        # Get gateway
        gateway_class = cls.GATEWAY_MAP.get(gateway_type)
        if not gateway_class:
            return {'success': False, 'error': 'Gateway not found'}

        gateway_instance = gateway_class(txn.gateway)

        # Verify payment
        verify_result = gateway_instance.verify_payment(request_data)

        if verify_result.get('success'):
            txn.complete(verify_result.get('raw_response'))
            return {
                'success': True,
                'transaction': txn,
                'redirect_url': txn.success_url or '/payment/success'
            }
        else:
            txn.status = 'failed'
            txn.gateway_response_message = verify_result.get('error', '')
            txn.save()
            return {
                'success': False,
                'error': verify_result.get('error'),
                'redirect_url': txn.failure_url or '/payment/failed'
            }


class ReconciliationService:
    """Bank statement reconciliation service."""

    @classmethod
    def auto_match(cls, statement_line):
        """Auto-match statement line to transactions."""
        suggestions = []

        # Try to match by amount and date proximity
        candidates = PaymentTransaction.objects.filter(
            tenant=statement_line.account.tenant,
            amount=abs(statement_line.amount),
            status='completed',
            is_reconciled=False
        ).exclude(
            bank_statement_line__isnull=False
        )

        for txn in candidates:
            score = 0
            reasons = []

            # Amount match (exact)
            if txn.amount == abs(statement_line.amount):
                score += 50
                reasons.append('Exact amount match')

            # Date proximity (within 3 days)
            date_diff = abs((txn.completed_at.date() - statement_line.date).days)
            if date_diff <= 3:
                score += 30
                reasons.append(f'Date within {date_diff} days')

            # Reference match
            if txn.gateway_transaction_id in statement_line.reference:
                score += 20
                reasons.append('Reference match')

            if score >= 50:
                suggestions.append({
                    'transaction_id': txn.id,
                    'transaction_ref': txn.transaction_id,
                    'score': score,
                    'reasons': reasons
                })

        # Sort by score
        suggestions.sort(key=lambda x: x['score'], reverse=True)
        statement_line.match_suggestions = suggestions[:5]
        statement_line.save()

        # Auto-match if high confidence
        if suggestions and suggestions[0]['score'] >= 90:
            cls.match_line(statement_line, PaymentTransaction.objects.get(id=suggestions[0]['transaction_id']))

        return suggestions

    @classmethod
    def match_line(cls, statement_line, transaction=None, invoice=None, bill=None):
        """Manually match statement line."""
        statement_line.matched_transaction = transaction
        statement_line.matched_invoice = invoice
        statement_line.matched_bill = bill
        statement_line.status = 'manual'
        statement_line.save()

        if transaction:
            transaction.is_reconciled = True
            transaction.reconciled_at = timezone.now()
            transaction.bank_statement_line = statement_line
            transaction.save()

        return True

    @classmethod
    def import_statement(cls, bank_account, file_data, file_format='csv'):
        """Import bank statement from file."""
        from .parsers import StatementParser

        parser = StatementParser.get_parser(file_format)
        parsed_data = parser.parse(file_data)

        # Create statement
        statement = BankStatement.objects.create(
            tenant=bank_account.tenant,
            account=bank_account,
            statement_date=parsed_data['statement_date'],
            start_date=parsed_data['start_date'],
            end_date=parsed_data['end_date'],
            opening_balance=parsed_data['opening_balance'],
            closing_balance=parsed_data['closing_balance']
        )

        # Create lines
        for line_data in parsed_data['transactions']:
            BankStatementLine.objects.create(
                statement=statement,
                account=bank_account,
                date=line_data['date'],
                bs_date=line_data.get('bs_date'),
                description=line_data['description'],
                reference=line_data.get('reference', ''),
                debit=line_data.get('debit', Decimal('0')),
                credit=line_data.get('credit', Decimal('0')),
                amount=line_data['amount'],
                running_balance=line_data['balance']
            )

        # Auto-match all lines
        for line in statement.lines.all():
            cls.auto_match(line)

        return statement