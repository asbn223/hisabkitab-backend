# apps/core/db/router.py
"""
Multi-tenant database router.
Currently supports single database with RLS.
Can be extended for schema-per-tenant or DB-per-tenant.
"""


class TenantRouter:
    """
    Database router for multi-tenant applications.
    """

    def db_for_read(self, model, **hints):
        """Return database for read operations."""
        return 'default'

    def db_for_write(self, model, **hints):
        """Return database for write operations."""
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        """
        Allow relations between models in same tenant.
        """
        # Get tenant IDs if available
        tenant1 = getattr(obj1, 'tenant_id', None)
        tenant2 = getattr(obj2, 'tenant_id', None)

        # Allow if both have same tenant or one is system model
        if tenant1 is None or tenant2 is None:
            return True

        return tenant1 == tenant2

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Allow migrations for all models.
        """
        return True

    def allow_syncdb(self, db, model):
        """
        Allow syncdb for all models.
        """
        return True