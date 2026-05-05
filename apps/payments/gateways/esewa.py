"""
eSewa payment gateway integration.
"""
import hashlib
import hmac
import base64
import json
import requests
from decimal import Decimal
from django.conf import settings
from .base import PaymentGatewayBase


class EsewaGateway(PaymentGatewayBase):
    """eSewa payment gateway implementation."""

    SANDBOX_URL = "https://rc-epay.esewa.com.np/api/epay/main/v2/form"
    PRODUCTION_URL = "https://epay.esewa.com.np/api/epay/main/v2/form"
    VERIFY_URL = "https://{env}.esewa.com.np/api/epay/transaction/status/"

    def __init__(self, gateway_config):
        super().__init__(gateway_config)
        self.is_sandbox = gateway_config.environment == 'sandbox'
        self.base_url = self.SANDBOX_URL if self.is_sandbox else self.PRODUCTION_URL

    def initialize_payment(self, amount, transaction_id, **kwargs):
        """Generate eSewa payment form data."""

        # eSewa requires amount without decimal for some implementations
        amount_float = float(amount)
        tax_amount = kwargs.get('tax_amount', 0)
        service_charge = kwargs.get('service_charge', 0)
        delivery_charge = kwargs.get('delivery_charge', 0)

        total_amount = amount_float + float(tax_amount) + float(service_charge) + float(delivery_charge)

        # Generate signature
        params = {
            'transaction_uuid': transaction_id,
            'product_code': self.config.merchant_id,
            'total_amount': total_amount,
        }

        message = f"{params['total_amount']},{params['transaction_uuid']},{params['product_code']}"
        signature = self._generate_signature(message)

        form_data = {
            'amount': amount_float,
            'tax_amount': tax_amount,
            'product_service_charge': service_charge,
            'product_delivery_charge': delivery_charge,
            'total_amount': total_amount,
            'transaction_uuid': transaction_id,
            'product_code': self.config.merchant_id,
            'signature': signature,
            'signed_field_names': 'total_amount,transaction_uuid,product_code',
            'success_url': self.get_callback_urls(None)['success'],
            'failure_url': self.get_callback_urls(None)['failure'],
        }

        return {
            'action_url': self.base_url,
            'method': 'POST',
            'fields': form_data
        }

    def verify_payment(self, gateway_response):
        """Verify eSewa payment using their API."""
        transaction_uuid = gateway_response.get('transaction_uuid')
        ref_id = gateway_response.get('ref_id')  # eSewa reference

        # Call verification API
        url = self.VERIFY_URL.format(
            env='rc' if self.is_sandbox else 'epay'
        )

        params = {
            'product_code': self.config.merchant_id,
            'total_amount': gateway_response.get('total_amount'),
            'transaction_uuid': transaction_uuid,
        }

        try:
            response = requests.get(url, params=params, timeout=30)
            data = response.json()

            if response.status_code == 200 and data.get('status') == 'COMPLETE':
                return {
                    'success': True,
                    'transaction_id': ref_id,
                    'amount': Decimal(str(data.get('total_amount', 0))),
                    'reference_id': ref_id,
                    'raw_response': data
                }
            else:
                return {
                    'success': False,
                    'error': data.get('message', 'Verification failed'),
                    'raw_response': data
                }

        except requests.RequestException as e:
            return {
                'success': False,
                'error': str(e)
            }

    def refund(self, original_transaction, amount):
        """eSewa refund - requires manual process or separate API."""
        # eSewa refunds typically done through merchant dashboard
        # or separate API endpoint
        return {
            'success': False,
            'error': 'Refund via dashboard required'
        }

    def _generate_signature(self, message):
        """Generate HMAC-SHA256 signature."""
        secret = self.config.merchant_key.encode('utf-8')
        signature = hmac.new(secret, message.encode('utf-8'), hashlib.sha256).digest()
        return base64.b64encode(signature).decode('utf-8')