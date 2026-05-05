"""
Base class for payment gateway integrations.
"""
from abc import ABC, abstractmethod
from decimal import Decimal


class PaymentGatewayBase(ABC):
    """Abstract base class for payment gateways."""

    def __init__(self, gateway_config):
        self.config = gateway_config
        self.tenant = gateway_config.tenant

    @abstractmethod
    def initialize_payment(self, amount, transaction_id, **kwargs):
        """Initialize payment and return redirect URL/form."""
        pass

    @abstractmethod
    def verify_payment(self, gateway_response):
        """Verify payment status from gateway callback."""
        pass

    @abstractmethod
    def refund(self, original_transaction, amount):
        """Process refund."""
        pass

    def calculate_fees(self, amount):
        """Calculate gateway fees."""
        if self.config.service_charge_percent > 0:
            return amount * (self.config.service_charge_percent / 100)
        return Decimal('0')

    def get_callback_urls(self, transaction):
        """Generate callback URLs."""
        from django.urls import reverse
        from django.conf import settings

        base_url = settings.SITE_URL

        return {
            'success': f"{base_url}/api/payments/callback/{self.config.gateway_type}/success/?txn={transaction.transaction_id}",
            'failure': f"{base_url}/api/payments/callback/{self.config.gateway_type}/failure/?txn={transaction.transaction_id}",
            'cancel': f"{base_url}/api/payments/callback/{self.config.gateway_type}/cancel/?txn={transaction.transaction_id}",
        }