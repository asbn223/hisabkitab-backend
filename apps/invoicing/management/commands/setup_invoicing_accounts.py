# apps/invoicing/management/commands/setup_invoicing_accounts.py
from django.core.management.base import BaseCommand
from apps.accounts.models import Account
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = 'Setup required accounts for invoicing'

    def handle(self, *args, **options):
        for tenant in Tenant.objects.filter(is_active=True):
            accounts = [
                ('1200', 'Accounts Receivable', 'asset'),
                ('2200', 'VAT Output', 'liability'),
                ('4100', 'Sales - Domestic', 'income'),
                ('4101', 'Sales - Retail', 'income'),
                ('4110', 'Sales - Export', 'income'),
            ]

            for code, name, acc_type in accounts:
                Account.objects.get_or_create(
                    tenant=tenant,
                    code=code,
                    defaults={
                        'name': name,
                        'type': acc_type,
                        'is_system': True,
                        'is_active': True
                    }
                )

            self.stdout.write(f"Setup accounts for {tenant.name}")