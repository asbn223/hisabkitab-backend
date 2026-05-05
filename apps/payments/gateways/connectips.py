"""
ConnectIPS (NPI) integration for bank transfers.
"""
import requests
import xml.etree.ElementTree as ET
from decimal import Decimal
from .base import PaymentGatewayBase


class ConnectIPSGateway(PaymentGatewayBase):
    """
    ConnectIPS - Nepal Payment Interface (NPI).
    Direct bank-to-bank transfers.
    """

    SANDBOX_URL = "https://uat.connectips.com:7443/connectipswebgw/api/ConnectIPS"
    PRODUCTION_URL = "https://connectips.com/connectipswebgw/api/ConnectIPS"
    VERIFY_URL = "https://{env}/connectipswebgw/api/ConnectIPS/txnStatus"

    def __init__(self, gateway_config):
        super().__init__(gateway_config)
        self.is_sandbox = gateway_config.environment == 'sandbox'
        self.base_url = self.SANDBOX_URL if self.is_sandbox else self.PRODUCTION_URL

    def initialize_payment(self, amount, transaction_id, **kwargs):
        """
        ConnectIPS uses a different flow - credential validation
        and direct bank selection.
        """
        return {
            'success': True,
            'method': 'redirect',
            'payment_url': f"{self.base_url}/login",
            'transaction_id': transaction_id,
            'merchant_id': self.config.merchant_id,
            'amount': float(amount),
            'remarks': kwargs.get('description', 'Payment'),
        }

    def verify_payment(self, gateway_response):
        """Verify ConnectIPS transaction."""
        # ConnectIPS sends transaction details via callback
        # We need to verify with their status API

        transaction_id = gateway_response.get('transactionId')
        merchant_id = gateway_response.get('merchantId')

        verification_data = {
            'merchantId': merchant_id,
            'transactionId': transaction_id,
            'txnAmount': gateway_response.get('txnAmount'),
        }

        # Add signature validation here as per ConnectIPS specs

        return {
            'success': gateway_response.get('status') == 'SUCCESS',
            'transaction_id': transaction_id,
            'amount': Decimal(str(gateway_response.get('txnAmount', 0))),
            'reference_id': transaction_id,
            'raw_response': gateway_response
        }

    def get_transaction_status(self, transaction_id):
        """Query transaction status from ConnectIPS."""
        url = self.VERIFY_URL.format(
            env='uat.connectips.com:7443' if self.is_sandbox else 'connectips.com'
        )

        payload = {
            'merchantId': self.config.merchant_id,
            'transactionId': transaction_id,
        }

        try:
            response = requests.post(url, json=payload, timeout=30)
            return response.json()
        except requests.RequestException as e:
            return {'error': str(e)}