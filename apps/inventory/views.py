# apps/inventory/views.py
"""
API views for inventory management.
"""
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, F, Q
from django.utils import timezone
from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from .models import InventoryItem, StockMovement, StockReservation, InventoryCount, SupplierPriceList, \
    InventoryCountLine
from .serializers import (
    InventoryItemListSerializer, InventoryItemDetailSerializer,
    StockMovementSerializer, StockAdjustmentSerializer,
    InventoryCountSerializer, InventoryCountLineSerializer,
    StockReservationSerializer, LowStockAlertSerializer,
    InventoryValuationSerializer, SupplierPriceListSerializer
)
from .services import (
    adjust_stock, reserve_stock, release_reservation,
    fulfill_reservation, process_count_adjustments,
    get_inventory_valuation, recalculate_average_cost
)
from core.db.locks import advisory_lock
from core.exceptions import InsufficientStockError
from apps.tenants.permissions import TenantPermission, IsAccountant


class InventoryItemViewSet(viewsets.ModelViewSet):
    """
    ViewSet for inventory items (SKU management).
    """
    permission_classes = [IsAuthenticated, TenantPermission]

    def get_queryset(self):
        """Filter by tenant with optional filters."""
        queryset = InventoryItem.objects.filter(
            tenant=self.request.tenant,
            is_active=True
        )

        # Apply filters
        category = self.request.query_params.get('category')
        low_stock = self.request.query_params.get('low_stock')
        search = self.request.query_params.get('search')
        track_inventory = self.request.query_params.get('track_inventory')

        if category:
            queryset = queryset.filter(category=category)
        if low_stock == 'true':
            queryset = queryset.filter(
                track_inventory=True,
                stock_quantity__lte=F('reorder_level')
            )
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search) |
                Q(barcode__icontains=search)
            )
        if track_inventory is not None:
            queryset = queryset.filter(track_inventory=track_inventory.lower() == 'true')

        return queryset

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return InventoryItemDetailSerializer
        return InventoryItemListSerializer

    def perform_create(self, serializer):
        """Set tenant and generate code if needed."""
        data = serializer.validated_data

        # Auto-generate code if not provided
        if not data.get('code'):
            from core.sequence import next_sequence
            data['code'] = next_sequence('SKU', self.request.tenant.id)

        # Set BS dates
        if not data.get('bs_date'):
            from core.bs_date import ad_to_bs
            data['bs_date'] = ad_to_bs(str(data.get('date', timezone.now().date())))

        serializer.save(tenant=self.request.tenant)

    @action(detail=True, methods=['get'])
    def movements(self, request, pk=None):
        """Get stock movement history."""
        item = self.get_object()
        movements = StockMovement.objects.filter(
            tenant=request.tenant,
            item=item
        ).order_by('-date', '-created_at')

        # Pagination
        page = self.paginate_queryset(movements)
        if page is not None:
            serializer = StockMovementSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = StockMovementSerializer(movements, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def adjust(self, request, pk=None):
        """
        Adjust stock quantity with advisory locking.
        """
        item = self.get_object()
        tenant = request.tenant

        serializer = StockAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        # Ensure item_id matches URL
        if data['item_id'] != item.id:
            return Response(
                {'error': 'Item ID mismatch'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with advisory_lock(tenant.id, 'inventory_item', item.id):
                result = adjust_stock(
                    tenant_id=tenant.id,
                    item_id=item.id,
                    adjustment_qty=data['adjustment_qty'],
                    unit_cost=data.get('unit_cost'),
                    reason=data['reason'],
                    date=data['date'],
                    notes=data.get('notes', ''),
                    created_by=str(request.user.id)
                )

                return Response(result)

        except InsufficientStockError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        """Get low stock alerts."""
        items = InventoryItem.objects.filter(
            tenant=request.tenant,
            is_active=True,
            track_inventory=True,
            stock_quantity__lte=F('reorder_level')
        ).exclude(reorder_level=0)

        alerts = []
        for item in items:
            shortage = item.reorder_level - item.stock_quantity
            suggested = max(item.reorder_quantity, shortage * 2)

            alerts.append({
                'item_id': item.id,
                'code': item.code,
                'name': item.name,
                'current_stock': str(item.stock_quantity),
                'reorder_level': str(item.reorder_level),
                'shortage': str(shortage),
                'suggested_order': str(suggested),
            })

        return Response(alerts)

    @action(detail=False, methods=['get'])
    def categories(self, request):
        """Get unique categories."""
        categories = InventoryItem.objects.filter(
            tenant=request.tenant,
            is_active=True
        ).values_list('category', flat=True).distinct()

        return Response([c for c in categories if c])

    @action(detail=False, methods=['get'])
    def valuation(self, request):
        """Get inventory valuation report."""
        as_of = request.query_params.get('as_of')
        data = get_inventory_valuation(request.tenant, as_of)
        return Response(data)

    @action(detail=True, methods=['post'])
    def recalculate_cost(self, request, pk=None):
        """Recalculate average cost from movement history."""
        item = self.get_object()

        if item.valuation_method != 'average':
            return Response(
                {'error': 'Only applicable for average cost valuation'},
                status=status.HTTP_400_BAD_REQUEST
            )

        new_cost = recalculate_average_cost(item)

        return Response({
            'item_id': item.id,
            'previous_cost': str(item.purchase_price),
            'new_cost': str(new_cost),
            'recalculated_at': timezone.now().isoformat()
        })


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only view of stock movements.
    Use item.adjust endpoint to create adjustments.
    """
    serializer_class = StockMovementSerializer
    permission_classes = [IsAuthenticated, TenantPermission]

    def get_queryset(self):
        """Filter by tenant."""
        queryset = StockMovement.objects.filter(
            tenant=self.request.tenant
        ).select_related('item')

        # Filters
        item_id = self.request.query_params.get('item_id')
        movement_type = self.request.query_params.get('type')
        from_date = self.request.query_params.get('from')
        to_date = self.request.query_params.get('to')
        batch = self.request.query_params.get('batch')

        if item_id:
            queryset = queryset.filter(item_id=item_id)
        if movement_type:
            queryset = queryset.filter(type=movement_type)
        if from_date:
            queryset = queryset.filter(date__gte=from_date)
        if to_date:
            queryset = queryset.filter(date__lte=to_date)
        if batch:
            queryset = queryset.filter(batch_number=batch)

        return queryset.order_by('-date', '-created_at')


class StockReservationViewSet(viewsets.ModelViewSet):
    """
    Manage stock reservations.
    """
    serializer_class = StockReservationSerializer
    permission_classes = [IsAuthenticated, TenantPermission]

    def get_queryset(self):
        return StockReservation.objects.filter(
            tenant=self.request.tenant,
            is_active=True
        ).select_related('item')

    def perform_create(self, serializer):
        """Create reservation with stock check."""
        item_id = serializer.validated_data['item'].id
        quantity = serializer.validated_data['quantity']

        try:
            reservation = reserve_stock(
                tenant_id=self.request.tenant.id,
                item_id=item_id,
                quantity=quantity,
                reserved_for_type=serializer.validated_data['reserved_for_type'],
                reserved_for_id=serializer.validated_data['reserved_for_id'],
                reserved_for_number=serializer.validated_data.get('reserved_for_number', ''),
                expires_at=serializer.validated_data.get('expires_at')
            )
            return reservation
        except InsufficientStockError as e:
            raise serializers.ValidationError(str(e))

    @action(detail=True, methods=['post'])
    def release(self, request, pk=None):
        """Release/cancel reservation."""
        reservation = self.get_object()
        release_reservation(reservation.id)
        return Response({'status': 'released'})

    @action(detail=True, methods=['post'])
    def fulfill(self, request, pk=None):
        """Fulfill reservation with actual quantity."""
        reservation = self.get_object()
        quantity = request.data.get('quantity', reservation.remaining_quantity)

        result = fulfill_reservation(reservation.id, Decimal(str(quantity)))
        return Response(result)


class InventoryCountViewSet(viewsets.ModelViewSet):
    """
    Physical stock count / stock take operations.
    """
    serializer_class = InventoryCountSerializer
    permission_classes = [IsAuthenticated, TenantPermission, IsAccountant]

    def get_queryset(self):
        return InventoryCount.objects.filter(
            tenant=self.request.tenant
        ).prefetch_related('lines', 'lines__item')

    def perform_create(self, serializer):
        """Create count with lines."""
        data = serializer.validated_data

        # Generate reference
        if not data.get('reference_number'):
            from core.sequence import next_sequence
            data['reference_number'] = next_sequence('COUNT', self.request.tenant.id)

        # Set BS date
        if not data.get('bs_count_date'):
            from core.bs_date import ad_to_bs
            data['bs_count_date'] = ad_to_bs(str(data['count_date']))

        count = serializer.save(
            tenant=self.request.tenant,
            created_by=str(self.request.user.id)
        )

        # Auto-populate lines if category specified
        if count.category:
            items = InventoryItem.objects.filter(
                tenant=count.tenant,
                category=count.category,
                is_active=True,
                track_inventory=True
            )

            for item in items:
                InventoryCountLine.objects.create(
                    count=count,
                    item=item,
                    system_quantity=item.stock_quantity
                )

        return count

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Start the count."""
        count = self.get_object()

        if count.status != 'draft':
            return Response(
                {'error': 'Count must be in draft status'},
                status=status.HTTP_400_BAD_REQUEST
            )

        count.status = 'in_progress'
        count.started_at = timezone.now()
        count.save()

        return Response(InventoryCountSerializer(count).data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Complete count and create adjustments."""
        count = self.get_object()

        if count.status != 'in_progress':
            return Response(
                {'error': 'Count must be in progress'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Process adjustments
        result = process_count_adjustments(
            count.id,
            processed_by=str(request.user.id)
        )

        count.status = 'completed'
        count.completed_at = timezone.now()
        count.save()

        return Response({
            'count': InventoryCountSerializer(count).data,
            'adjustments': result
        })

    @action(detail=True, methods=['get'])
    def lines(self, request, pk=None):
        """Get count lines."""
        count = self.get_object()
        lines = count.lines.all()

        # Filter uncounted
        uncounted = request.query_params.get('uncounted')
        if uncounted == 'true':
            lines = lines.filter(is_counted=False)

        serializer = InventoryCountLineSerializer(lines, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['patch'], url_path='lines/(?P<line_id>[^/.]+)')
    def update_line(self, request, pk=None, line_id=None):
        """Update a count line with counted quantity."""
        count = self.get_object()

        try:
            line = count.lines.get(id=line_id)
        except InventoryCountLine.DoesNotExist:
            return Response(
                {'error': 'Line not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        counted_qty = request.data.get('counted_quantity')
        notes = request.data.get('notes', '')

        if counted_qty is not None:
            line.counted_quantity = Decimal(str(counted_qty))
            line.difference = line.counted_quantity - line.system_quantity
            line.is_counted = True
            line.counted_by = str(request.user.id)
            line.counted_at = timezone.now()

        if notes:
            line.notes = notes

        line.save()

        return Response(InventoryCountLineSerializer(line).data)


class SupplierPriceListViewSet(viewsets.ModelViewSet):
    """
    Manage supplier pricing.
    """
    serializer_class = SupplierPriceListSerializer
    permission_classes = [IsAuthenticated, TenantPermission]

    def get_queryset(self):
        queryset = SupplierPriceList.objects.filter(
            tenant=self.request.tenant
        ).select_related('item')

        # Filters
        supplier_id = self.request.query_params.get('supplier_id')
        item_id = self.request.query_params.get('item_id')
        preferred = self.request.query_params.get('preferred')

        if supplier_id:
            queryset = queryset.filter(supplier_id=supplier_id)
        if item_id:
            queryset = queryset.filter(item_id=item_id)
        if preferred == 'true':
            queryset = queryset.filter(is_preferred=True)

        # Only valid prices
        from datetime import date
        queryset = queryset.filter(
            Q(valid_until__isnull=True) | Q(valid_until__gte=date.today())
        )

        return queryset.order_by('item__code')

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)

    @action(detail=False, methods=['get'])
    def best_prices(self, request):
        """Get best (lowest) price for each item."""
        from django.db.models import Min, Subquery, OuterRef

        # Subquery to get minimum price per item
        min_prices = SupplierPriceList.objects.filter(
            tenant=request.tenant,
            item=OuterRef('item')
        ).values('item').annotate(
            min_price=Min('unit_price')
        ).values('min_price')

        best_prices = SupplierPriceList.objects.filter(
            tenant=request.tenant,
            unit_price__in=Subquery(min_prices)
        ).select_related('item')

        serializer = self.get_serializer(best_prices, many=True)
        return Response(serializer.data)