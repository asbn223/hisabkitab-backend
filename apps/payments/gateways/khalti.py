"""
Khalti payment gateway integration.
"""
import requests
from decimal import Decimal
from .base import PaymentGatewayBase


class KhaltiGateway(PaymentGatewayBase):
    """Khalti wallet payment implementation."""

    SANDBOX_URL = "https://a.khalti.com/api/v2/epayment/initiate/"
    VERIFY_URL = "https://a.khalti.com/api/v2/epayment/lookup/"
    PRODUCTION_URL = "https://khalti.com/api/v2/epayment/initiate/"

    def __init__(self, gateway_config):
        super().__init__(gateway_config)
        self.is_sandbox = gateway_config.environment == 'sandbox'
        self.base_url = self.SANDBOX_URL if self.is_sandbox else self.PRODUCTION_URL
        self.headers = {
            'Authorization': f"Key {self.config.api_key}",
            'Content-Type': 'application/json',
        }

    def initialize_payment(self, amount, transaction_id, **kwargs):
        """Initialize Khalti ePayment."""

        # Khalti amount in paisa (multiply by 100)
        amount_paisa = int(amount * 100)

        payload = {
            'return_url': self.get_callback_urls(None)['success'],
            'website_url': kwargs.get('website_url', ''),
            'amount': amount_paisa,
            'purchase_order_id': transaction_id,
            'purchase_order_name': kwargs.get('description', 'Payment'),
            'customer_info': {
                'name': kwargs.get('customer_name', ''),
                'email': kwargs.get('customer_email', ''),
                'phone': kwargs.get('customer_phone', ''),
            }
        }

        try:
            response = requests.post(
                self.base_url,
                headers=self.headers,
                json=payload,
                timeout=30
            )
            data = response.json()

            if response.status_code == 200:
                return {
                    'success': True,
                    'payment_url': data.get('payment_url'),
                    'pidx': data.get('pidx'),  # Khalti payment ID
                    'raw_response': data
                }
            else:
                return {
                    'success': False,
                    'error': data.get('detail', 'Failed to initialize'),
                    'raw_response': data
                }

        except requests.RequestException as e:
            return {
                'success': False,
                'error': str(e)
            }

    def verify_payment(self, gateway_response):
        """Verify Khalti payment using pidx."""
        pidx = gateway_response.get('pidx')

        if not pidx:
            return {'success': False, 'error': 'No pidx provided'}

        try:
            response = requests.post(
                self.VERIFY_URL,
                headers=self.headers,
                json={'pidx': pidx},
                timeout=30
            )
            data = response.json()

            if response.status_code == 200:
                status = data.get('status')
                if status == 'Completed':
                    return {
                        'success': True,
                        'transaction_id': data.get('transaction_id'),
                        'amount': Decimal(str(data.get('total_amount', 0))) / 100,  # Convert from paisa
                        'reference_id': pidx,
                        'raw_response': data
                    }
                else:
                    return {
                        'success': False,
                        'error': f"Payment status: {status}",
                        'raw_response': data
                    }
            else:
                return {
                    'success': False,
                    'error': data.get('detail', 'Verification failed'),
                    'raw_response': data
                }

        except requests.RequestException as e:
            return {
                'success': False,
                'error': str(e)
            }

    def refund(self, original_transaction, amount):
        """Khalti refund API."""
        # Khalti refund endpoint
        url = "https://a.khalti.com/api/v2/epayment/refund/" if self.is_sandbox else "https://khalti.com/api/v2/epayment/refund/"

        try:
            response = requests.post(
                url,
                headers=self.headers,
                json={
                    'transaction_id': original_transaction.gateway_transaction_id,
                    'amount': int(amount * 100),  # Paisa
                },
                timeout=30
            )
            return {
                'success': response.status_code == 200,
                'raw_response': response.json()
            }
        except requests.RequestException as e:
            return {
                'success': False,
                'error': str(e)
            }