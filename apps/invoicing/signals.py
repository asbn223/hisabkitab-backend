from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import InvoiceLine, InvoicePayment


@receiver([post_save, post_delete], sender=InvoiceLine)
def recalculate_invoice(sender, instance, **kwargs):
    """Recalculate invoice totals when lines change."""
    instance.invoice.calculate_totals()


@receiver(post_delete, sender=InvoicePayment)
def update_on_payment_delete(sender, instance, **kwargs):
    """Update invoice when payment is deleted."""
    invoice = instance.invoice
    total = sum(p.amount for p in invoice.payments.all())
    invoice.amount_paid = total
    invoice.amount_due = invoice.total_amount - total

    if invoice.amount_due >= invoice.total_amount:
        invoice.status = 'sent'
        invoice.paid_at = None
    elif invoice.amount_paid > 0:
        invoice.status = 'partial'

    invoice.save()