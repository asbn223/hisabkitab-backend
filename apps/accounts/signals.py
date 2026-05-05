# apps/accounts/signals.py
"""
Signals for accounting models.
"""
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver

from .models import Transaction, LedgerEntry


@receiver(post_save, sender=Transaction)
def log_transaction_change(sender, instance, created, **kwargs):
    """Log transaction changes to audit."""
    from apps.audit.models import AuditLog

    action = 'created' if created else 'updated'

    # Only log posted transactions or status changes
    if instance.status == 'posted' or not created:
        AuditLog.objects.create(
            tenant=instance.tenant,
            entity_type='transaction',
            entity_id=instance.id,
            action=action,
            new_data={
                'reference': instance.reference_number,
                'status': instance.status,
                'total': str(instance.total_debit),
            }
        )


@receiver(pre_delete, sender=LedgerEntry)
def prevent_delete_posted_entry(sender, instance, **kwargs):
    """Prevent deletion of entries in posted transactions."""
    if instance.transaction.status == 'posted':
        raise PermissionError(
            'Cannot delete ledger entry from posted transaction. '
            'Cancel or reverse the transaction instead.'
        )