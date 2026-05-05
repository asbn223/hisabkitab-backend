# apps/core/management/commands/setup_rls.py
"""
Setup PostgreSQL Row Level Security policies.
"""
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Setup Row Level Security policies for all tenant-scoped tables'

    def handle(self, *args, **options):
        tables = [
            'tenants_tenant',
            'tenants_tenantuser',
            'accounts_account',
            'accounts_transaction',
            'accounts_ledgerentry',
            'inventory_inventoryitem',
            'inventory_stockmovement',
            'invoicing_invoice',
            'invoicing_invoiceline',
            'purchases_purchase',
            'purchases_purchaseline',
            'payments_payment',
            'tax_taxrecord',
            'audit_auditlog',
        ]

        with connection.cursor() as cursor:
            for table in tables:
                # Enable RLS
                cursor.execute(f'ALTER TABLE IF EXISTS {table} ENABLE ROW LEVEL SECURITY;')

                # Drop existing policy if exists
                cursor.execute(f"""
                    DO $$
                    BEGIN
                        DROP POLICY IF EXISTS tenant_isolation_policy ON {table};
                    END
                    $$;
                """)

                # Create policy
                if table == 'tenants_tenant':
                    cursor.execute(f"""
                        CREATE POLICY tenant_isolation_policy ON {table}
                            USING (id = current_setting('app.current_tenant', true)::int);
                    """)
                else:
                    cursor.execute(f"""
                        CREATE POLICY tenant_isolation_policy ON {table}
                            USING (tenant_id = current_setting('app.current_tenant', true)::int);
                    """)

                # Force RLS for table owner
                cursor.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY;')

                self.stdout.write(self.style.SUCCESS(f'✓ RLS enabled for {table}'))

        self.stdout.write(self.style.SUCCESS('\n✓ All RLS policies configured successfully'))