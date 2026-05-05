# apps/inventory/signals.py
"""
Signals for inventory models.
"""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import InventoryItem, StockMovement, StockReservation


@receiver(pre_save, sender=InventoryItem)
def calculate_available_quantity(sender, instance, **kwargs):
    """Ensure available quantity is calculated before save."""
    instance.available_quantity = instance.stock_quantity - instance.reserved_quantity
    if instance.available_quantity < 0:
        instance.available_quantity = 0


@receiver(post_save, sender=StockMovement)
def log_large_movement(sender, instance, created, **kwargs):
    """Log significant stock movements."""
    if not created:
        return

    # Alert on large adjustments
    if instance.type == 'adjustment' and abs(instance.quantity) > 100:
        # Could send notification/email
        pass


@receiver(post_save, sender=StockReservation)
def check_expired_reservations(sender, instance, created, **kwargs):
    """Auto-release expired reservations."""
    if not created or not instance.expires_at:
        return

    # Schedule task to release at expiry
    from celery import current_app
    from datetime import datetime

    if instance.expires_at > datetime.now():
        current_app.send_task(
            'apps.inventory.tasks.release_expired_reservation',
            args=[instance.id],
            eta=instance.expires_at
        )