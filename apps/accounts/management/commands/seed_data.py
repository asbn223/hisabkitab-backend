# apps/core/management/commands/seed_data.py
"""
Seed initial data for development/testing.
"""
from django.core.management.base import BaseCommand
from apps.tenants.models import Tenant, TenantUser
from apps.accounts.services import seed_chart_of_accounts


class Command(BaseCommand):
    help = 'Seed database with initial data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            type=str,
            help='Tenant name to create',
            default='Demo Business'
        )
        parser.add_argument(
            '--slug',
            type=str,
            help='Tenant slug',
            default='demo-business'
        )

    def handle(self, *args, **options):
        tenant_name = options['tenant']
        slug = options['slug']

        # Create tenant
        tenant, created = Tenant.objects.get_or_create(
            slug=slug,
            defaults={
                'name': tenant_name,
                'pan': '123456789',
                'vat_number': '301234567',
                'address': 'Kathmandu, Nepal',
                'phone': '01-4444444',
                'email': 'admin@demo.com',
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Created tenant: {tenant_name}'))

            # Seed chart of accounts
            seed_chart_of_accounts(tenant)
            self.stdout.write(self.style.SUCCESS('✓ Seeded chart of accounts'))
        else:
            self.stdout.write(self.style.WARNING(f'Tenant {slug} already exists'))

        self.stdout.write(self.style.SUCCESS('\n✓ Seeding complete'))