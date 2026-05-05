# apps/inventory/services.py
"""
Business logic for inventory operations.
"""
from decimal import Decimal
from typing import Optional, Dict, List
import datetime

from django.db import transaction
from django.db.models import Sum, F
from django.utils import timezone

from .models import InventoryItem, StockMovement, StockReservation, InventoryCount, InventoryCountLine
from core.db.locks import advisory_lock
from core.decimal.decimal_config import fiscal_round
from core.bs_date import ad_to_bs, get_current_bs_date
from core.exceptions import InsufficientStockError
from core.sequence import next_sequence


def adjust_stock(
        tenant_id: int,
        item_id: int,
        adjustment_qty: Decimal,
        unit_cost: Optional[Decimal] = None,
        reason: str = '',
        date: Optional[datetime.date] = None,
        notes: str = '',
        reference_type: str = 'manual_adjustment',
        reference_id: Optional[int] = None,
        created_by: str = ''
) -> Dict:
    """
    Adjust stock quantity with full audit trail.

    Args:
        adjustment_qty: Positive to add, negative to remove
        unit_cost: Cost per unit (required for positive adjustments)

    Returns:
        Dict with new stock level and movement details
        :param created_by:
        :param reference_id:
        :param reference_type:
        :param notes:
        :param date:
        :param unit_cost:
        :param adjustment_qty:
        :param reason:
        :param item_id:
        :param tenant_id:
    """
    with transaction.atomic():
        # Lock and refresh item
        item = InventoryItem.objects.select_for_update().get(
            id=item_id,
            tenant_id=tenant_id
        )

        if not item.track_inventory:
            raise ValueError('Cannot adjust non-tracked item')

        old_stock = item.stock_quantity
        new_stock = old_stock + Decimal(str(adjustment_qty))

        # Validate sufficient stock for negative adjustment
        if adjustment_qty < 0 and new_stock < 0:
            raise InsufficientStockError(
                f'Cannot reduce stock below zero. Current: {old_stock}, '
                f'Adjustment: {adjustment_qty}'
            )

        # Determine movement type
        if adjustment_qty > 0:
            movement_type = 'adjustment' if reference_type == 'manual_adjustment' else 'receipt'
        else:
            movement_type = 'adjustment' if reference_type == 'manual_adjustment' else 'issue'

        # Calculate unit cost
        if unit_cost is None and adjustment_qty > 0:
            unit_cost = item.purchase_price or item.standard_cost or Decimal('0')

        # Create movement record
        if date is None:
            from datetime import date as dt
            date = dt.today()

        movement = StockMovement.objects.create(
            tenant_id=tenant_id,
            item=item,
            type=movement_type,
            quantity=adjustment_qty,
            unit_cost=fiscal_round(unit_cost, 4) if unit_cost else None,
            total_cost=fiscal_round(abs(adjustment_qty) * (unit_cost or 0), 4) if unit_cost else None,
            reference_type=reference_type,
            reference_id=reference_id,
            date=date,
            bs_date=ad_to_bs(str(date)),
            notes=notes,
            reason=reason,
            created_by=created_by
        )

        # Update item stock
        item.stock_quantity = fiscal_round(new_stock, 4)

        # Update average cost if receipt and using average valuation
        if adjustment_qty > 0 and item.valuation_method == 'average' and unit_cost:
            # Weighted average: (old_stock * old_cost + new_qty * new_cost) / total
            if old_stock > 0:
                old_value = old_stock * item.purchase_price
                new_value = adjustment_qty * unit_cost
                new_avg = (old_value + new_value) / (old_stock + adjustment_qty)
                item.purchase_price = fiscal_round(new_avg, 4)
            else:
                item.purchase_price = fiscal_round(unit_cost, 4)

        item.save()

        # Create accounting transaction if significant value
        if movement.total_cost and movement.total_cost > 1000:
            _create_inventory_adjustment_journal(movement)

        return {
            'item_id': item.id,
            'item_code': item.code,
            'previous_stock': str(old_stock),
            'adjustment': str(adjustment_qty),
            'new_stock': str(item.stock_quantity),
            'movement_id': movement.id,
            'unit_cost': str(unit_cost) if unit_cost else None,
        }


def reserve_stock(
        tenant_id: int,
        item_id: int,
        quantity: Decimal,
        reserved_for_type: str,
        reserved_for_id: int,
        reserved_for_number: str = '',
        expires_at: Optional[datetime.datetime] = None
) -> StockReservation:
    """
    Reserve stock for an order.

    Args:
        quantity: Amount to reserve

    Returns:
        StockReservation object

    Raises:
        InsufficientStockError: If not enough available stock
        :param expires_at:
        :param reserved_for_number:
        :param reserved_for_id:
        :param reserved_for_type:
        :param quantity:
        :param item_id:
        :param tenant_id:
    """
    with advisory_lock(tenant_id, 'inventory_item', item_id):
        item = InventoryItem.objects.select_for_update().get(
            id=item_id,
            tenant_id=tenant_id
        )

        available = item.stock_quantity - item.reserved_quantity

        if available < quantity:
            raise InsufficientStockError(
                f'Cannot reserve {quantity}. Available: {available}, '
                f'Stock: {item.stock_quantity}, Reserved: {item.reserved_quantity}'
            )

        # Update reserved quantity
        item.reserved_quantity += quantity
        item.save()

        # Create reservation record
        reservation = StockReservation.objects.create(
            tenant_id=tenant_id,
            item=item,
            quantity=quantity,
            reserved_for_type=reserved_for_type,
            reserved_for_id=reserved_for_id,
            reserved_for_number=reserved_for_number,
            expires_at=expires_at
        )

        return reservation


def release_reservation(reservation_id: int) -> Dict:
    """
    Release/cancel a reservation.
    """
    with transaction.atomic():
        reservation = StockReservation.objects.select_related('item').get(id=reservation_id)

        if not reservation.is_active:
            return {'status': 'already_released'}

        # Reduce reserved quantity
        item = reservation.item
        item.reserved_quantity -= reservation.quantity
        if item.reserved_quantity < 0:
            item.reserved_quantity = Decimal('0')
        item.save()

        # Mark reservation inactive
        reservation.is_active = False
        reservation.save()

        return {
            'reservation_id': reservation.id,
            'released_quantity': str(reservation.quantity),
            'item_id': item.id,
            'new_reserved_qty': str(item.reserved_quantity)
        }


def fulfill_reservation(reservation_id: int, quantity: Decimal) -> Dict:
    """
    Fulfill part or all of a reservation.

    Args:
        quantity: Amount actually used (may be less than reserved)
        :param reservation_id:
    """
    with transaction.atomic():
        reservation = StockReservation.objects.select_related('item').get(id=reservation_id)

        if not reservation.is_active:
            raise ValueError('Reservation is not active')

        if quantity > reservation.remaining_quantity:
            raise ValueError(f'Cannot fulfill more than reserved: {reservation.remaining_quantity}')

        # Update fulfilled quantity
        reservation.fulfilled_quantity += quantity
        item = reservation.item

        # Reduce stock and reserved quantity
        item.stock_quantity -= quantity
        item.reserved_quantity -= quantity

        if item.stock_quantity < 0:
            item.stock_quantity = Decimal('0')
        if item.reserved_quantity < 0:
            item.reserved_quantity = Decimal('0')

        item.save()

        # Auto-complete if fully fulfilled
        if reservation.fulfilled_quantity >= reservation.quantity:
            reservation.is_active = False

        reservation.save()

        return {
            'reservation_id': reservation.id,
            'fulfilled': str(quantity),
            'total_fulfilled': str(reservation.fulfilled_quantity),
            'remaining': str(reservation.remaining_quantity),
            'is_complete': not reservation.is_active
        }


def process_count_adjustments(count_id: int, processed_by: str) -> List[Dict]:
    """
    Process inventory count and create stock adjustments.

    Args:
        count_id: InventoryCount ID
        processed_by: User ID

    Returns:
        List of adjustment results
    """
    count = InventoryCount.objects.prefetch_related('lines').get(id=count_id)
    results = []

    for line in count.lines.filter(is_counted=True, is_adjusted=False):
        if line.difference == 0:
            continue

        # Determine reason based on difference direction
        if line.difference > 0:
            reason = 'Stock count surplus'
        else:
            reason = 'Stock count shortage'

        # Create adjustment
        result = adjust_stock(
            tenant_id=count.tenant_id,
            item_id=line.item_id,
            adjustment_qty=line.difference,
            unit_cost=line.item.purchase_price if line.difference > 0 else None,
            reason=reason,
            date=count.count_date,
            notes=f'Physical count: {line.counted_quantity}, System: {line.system_quantity}',
            reference_type='inventory_count',
            reference_id=count.id,
            created_by=processed_by
        )

        line.is_adjusted = True
        line.save()

        results.append(result)

    return results


def recalculate_average_cost(item: InventoryItem) -> Decimal:
    """
    Recalculate average cost from movement history.

    Args:
        item: InventoryItem to recalculate

    Returns:
        New average cost
    """
    movements = StockMovement.objects.filter(
        tenant=item.tenant,
        item=item,
        type__in=['receipt', 'adjustment', 'return_in'],
        quantity__gt=0
    )

    total_qty = Decimal('0')
    total_value = Decimal('0')

    for movement in movements:
        if movement.unit_cost:
            qty = abs(movement.quantity)
            total_qty += qty
            total_value += qty * movement.unit_cost

    if total_qty > 0:
        new_avg = fiscal_round(total_value / total_qty, 4)
    else:
        new_avg = item.standard_cost or Decimal('0')

    # Update item
    item.purchase_price = new_avg
    item.save()

    return new_avg


def get_inventory_valuation(tenant, as_of=None) -> List[Dict]:
    """
    Get inventory valuation by category.

    Args:
        tenant: Tenant instance
        as_of: Date string (optional)

    Returns:
        List of category valuations
    """
    items = InventoryItem.objects.filter(
        tenant=tenant,
        is_active=True,
        track_inventory=True
    )

    # Calculate by category
    from django.db.models import Count, Sum as AggrSum

    categories = items.values('category').annotate(
        item_count=Count('id'),
        total_qty=AggrSum('stock_quantity'),
        total_val=AggrSum(F('stock_quantity') * F('purchase_price'))
    ).order_by('category')

    result = []
    for cat in categories:
        qty = cat['total_qty'] or Decimal('0')
        val = cat['total_val'] or Decimal('0')

        result.append({
            'category': cat['category'] or 'Uncategorized',
            'item_count': cat['item_count'],
            'total_quantity': str(fiscal_round(qty, 4)),
            'total_value': str(fiscal_round(val, 2)),
            'avg_unit_cost': str(fiscal_round(val / qty, 4)) if qty > 0 else '0'
        })

    return result


def _create_inventory_adjustment_journal(movement: StockMovement):
    """
    Create accounting journal entry for inventory adjustment.
    """
    from apps.accounts.services import create_auto_transaction

    item = movement.item

    # Determine accounts
    inventory_account = item.inventory_account
    if not inventory_account:
        from apps.accounts.models import Account
        inventory_account = Account.objects.get(tenant=movement.tenant, code='10302')

    adjustment_account = None
    if movement.quantity > 0:
        # Gain - credit adjustment account, debit inventory
        from apps.accounts.models import Account
        adjustment_account = Account.objects.filter(
            tenant=movement.tenant,
            code='40202'  # Other Income
        ).first()
    else:
        # Loss - debit adjustment account, credit inventory
        from apps.accounts.models import Account
        adjustment_account = Account.objects.filter(
            tenant=movement.tenant,
            code='50601'  # Bad Debt/Adjustment Expense
        ).first()

    if not adjustment_account:
        return  # Skip if accounts not configured

    entries = []
    if movement.quantity > 0:
        # Gain
        entries = [
            {'account_id': inventory_account.id, 'debit': str(movement.total_cost), 'credit': '0'},
            {'account_id': adjustment_account.id, 'debit': '0', 'credit': str(movement.total_cost)},
        ]
    else:
        # Loss
        entries = [
            {'account_id': adjustment_account.id, 'debit': str(movement.total_cost), 'credit': '0'},
            {'account_id': inventory_account.id, 'debit': '0', 'credit': str(movement.total_cost)},
        ]

    create_auto_transaction(
        tenant=movement.tenant,
        narration=f'Inventory adjustment: {movement.item.code} ({movement.reason})',
        entries=entries,
        source_type='stock_movement',
        source_id=movement.id,
        date=movement.date,
        created_by=movement.created_by or 'system'
    )


def issue_stock_for_invoice(
        tenant_id: int,
        item_id: int,
        quantity: Decimal,
        unit_price: Decimal,
        invoice_id: int,
        invoice_number: str,
        date=None,
        created_by: str = ''
) -> StockMovement:
    """
    Issue stock for sales invoice.

    Args:
        unit_price: Selling price (for revenue calculation)

    Returns:
        Created StockMovement
    """
    if date is None:
        from datetime import date as dt
        date = dt.today()

    item = InventoryItem.objects.get(id=item_id, tenant_id=tenant_id)

    if not item.track_inventory:
        return None  # No stock movement for non-tracked items

    # Check available stock
    available = item.stock_quantity - item.reserved_quantity
    if available < quantity:
        raise InsufficientStockError(
            f'Insufficient stock for {item.code}. '
            f'Available: {available}, Required: {quantity}'
        )

    # Use FIFO/LIFO/Average cost
    unit_cost = _get_issue_cost(item, quantity)

    # Create movement
    movement = StockMovement.objects.create(
        tenant_id=tenant_id,
        item=item,
        type='issue',
        quantity=-quantity,  # Negative for out
        unit_cost=unit_cost,
        total_cost=fiscal_round(quantity * unit_cost, 4),
        reference_type='invoice',
        reference_id=invoice_id,
        reference_number=invoice_number,
        date=date,
        bs_date=ad_to_bs(str(date)),
        created_by=created_by
    )

    # Update stock
    item.stock_quantity -= quantity
    item.save()

    return movement


def receive_stock_for_purchase(
        tenant_id: int,
        item_id: int,
        quantity: Decimal,
        unit_cost: Decimal,
        purchase_id: int,
        purchase_number: str,
        date=None,
        created_by: str = ''
) -> StockMovement:
    """
    Receive stock from purchase.
    """
    if date is None:
        from datetime import date as dt
        date = dt.today()

    item = InventoryItem.objects.get(id=item_id, tenant_id=tenant_id)

    movement = StockMovement.objects.create(
        tenant_id=tenant_id,
        item=item,
        type='receipt',
        quantity=quantity,
        unit_cost=fiscal_round(unit_cost, 4),
        total_cost=fiscal_round(quantity * unit_cost, 4),
        reference_type='purchase',
        reference_id=purchase_id,
        reference_number=purchase_number,
        date=date,
        bs_date=ad_to_bs(str(date)),
        created_by=created_by
    )

    # Update stock and cost
    old_stock = item.stock_quantity

    if item.valuation_method == 'average' and old_stock > 0:
        # Weighted average
        old_value = old_stock * item.purchase_price
        new_value = quantity * unit_cost
        item.purchase_price = fiscal_round((old_value + new_value) / (old_stock + quantity), 4)
    elif item.valuation_method in ['fifo', 'lifo']:
        # Store cost layer for later retrieval
        _store_cost_layer(item.id, quantity, unit_cost, date)
        item.purchase_price = fiscal_round(unit_cost, 4)  # Last price
    else:
        item.purchase_price = fiscal_round(unit_cost, 4)

    item.stock_quantity += quantity
    item.save()

    return movement


def _get_issue_cost(item: InventoryItem, quantity: Decimal) -> Decimal:
    """
    Get unit cost for stock issue based on valuation method.
    """
    if item.valuation_method == 'standard':
        return item.standard_cost

    if item.valuation_method == 'average':
        return item.purchase_price

    if item.valuation_method == 'fifo':
        return _get_fifo_cost(item.id, quantity)

    if item.valuation_method == 'lifo':
        return _get_lifo_cost(item.id, quantity)

    return item.purchase_price or Decimal('0')


# Cost layer storage for FIFO/LIFO (simplified - use dedicated model for production)
_cost_layers = {}  # item_id -> list of (qty, cost, date)


def _store_cost_layer(item_id: int, quantity: Decimal, cost: Decimal, date):
    """Store cost layer for FIFO/LIFO."""
    if item_id not in _cost_layers:
        _cost_layers[item_id] = []
    _cost_layers[item_id].append({
        'qty': quantity,
        'cost': cost,
        'date': date
    })


def _get_fifo_cost(item_id: int, quantity: Decimal) -> Decimal:
    """Get FIFO cost for issue."""
    layers = _cost_layers.get(item_id, [])
    if not layers:
        return Decimal('0')

    # Sort by date (oldest first)
    layers.sort(key=lambda x: x['date'])

    total_cost = Decimal('0')
    remaining = quantity

    for layer in layers[:]:  # Copy to allow modification
        if remaining <= 0:
            break

        take = min(remaining, layer['qty'])
        total_cost += take * layer['cost']
        remaining -= take
        layer['qty'] -= take

        if layer['qty'] <= 0:
            layers.remove(layer)

    if remaining > 0:
        # Not enough layers, use last known price
        total_cost += remaining * layers[-1]['cost'] if layers else Decimal('0')

    return fiscal_round(total_cost / quantity, 4) if quantity > 0 else Decimal('0')


def _get_lifo_cost(item_id: int, quantity: Decimal) -> Decimal:
    """Get LIFO cost for issue."""
    layers = _cost_layers.get(item_id, [])
    if not layers:
        return Decimal('0')

    # Sort by date (newest first)
    layers.sort(key=lambda x: x['date'], reverse=True)

    total_cost = Decimal('0')
    remaining = quantity

    for layer in layers[:]:
        if remaining <= 0:
            break

        take = min(remaining, layer['qty'])
        total_cost += take * layer['cost']
        remaining -= take
        layer['qty'] -= take

        if layer['qty'] <= 0:
            layers.remove(layer)

    if remaining > 0:
        total_cost += remaining * layers[-1]['cost'] if layers else Decimal('0')

    return fiscal_round(total_cost / quantity, 4) if quantity > 0 else Decimal('0')