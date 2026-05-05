# apps/audit/models.py
from django.db import models
from django.contrib.postgres.fields import JSONField


class AuditLog(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, db_index=True)
    entity_type = models.CharField(max_length=50, db_index=True)
    entity_id = models.IntegerField(db_index=True)
    action = models.CharField(max_length=20)  # create, update, delete, post, login
    changed_by = models.CharField(max_length=255)
    old_data = models.JSONField(default=dict)
    new_data = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'audit_logs'
        indexes = [
            models.Index(fields=['tenant', 'entity_type', 'entity_id', 'created_at']),
            models.Index(fields=['tenant', 'action', 'created_at']),
        ]

    @classmethod
    def log_change(cls, instance, action, user_id, request=None, old_data=None):
        """
        Helper method to create audit log entry.
        """
        from apps.tenants.middleware import get_current_tenant

        tenant = get_current_tenant()
        if not tenant:
            return None

        data = {
            'tenant': tenant,
            'entity_type': instance.__class__.__name__.lower(),
            'entity_id': instance.id,
            'action': action,
            'changed_by': str(user_id),
            'new_data': cls._serialize_instance(instance),
        }

        if old_data:
            data['old_data'] = old_data

        if request:
            data['ip_address'] = request.META.get('REMOTE_ADDR')
            data['user_agent'] = request.META.get('HTTP_USER_AGENT', '')[:255]

        return cls.objects.create(**data)

    @staticmethod
    def _serialize_instance(instance):
        """
        Serialize model instance to dict.
        """
        from django.db.models import Model
        data = {}
        for field in instance._meta.fields:
            value = getattr(instance, field.name)
            if isinstance(value, Model):
                data[field.name] = value.id
            else:
                data[field.name] = str(value) if value is not None else None
        return data