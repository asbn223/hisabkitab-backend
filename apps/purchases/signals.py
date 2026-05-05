from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import PurchaseOrderLine, SupplierBillLine, SupplierPayment


@receiver([post_save, post_delete], sender=PurchaseOrderLine)
def update_po_totals(sender, instance, **kwargs):
    """Recalculate PO totals when lines change."""
    instance.po.calculate_totals()


@receiver([post_save, post_delete], sender=SupplierBillLine)
def update_bill_totals(sender, instance, **kwargs):
    """Recalculate bill totals when lines change."""
    instance.bill.calculate_totals()


@receiver(post_delete, sender=SupplierPayment)
def update_on_payment_delete(sender, instance, **kwargs):
    """Update bill when payment deleted."""
    bill = instance.bill
    total = sum(p.amount for p in bill.payments.all())
    bill.amount_paid = total
    bill.amount_due = bill.total_amount - total

    if bill.amount_due >= bill.total_amount:
        bill.status = 'confirmed'
    elif bill.amount_paid > 0:
        bill.status = 'partial'

    bill.save()