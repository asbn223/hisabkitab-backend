# apps/inventory/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    InventoryItemViewSet, StockMovementViewSet,
    StockReservationViewSet, InventoryCountViewSet,
    SupplierPriceListViewSet
)

router = DefaultRouter()
router.register(r'items', InventoryItemViewSet, basename='inventoryitem')
router.register(r'movements', StockMovementViewSet, basename='stockmovement')
router.register(r'reservations', StockReservationViewSet, basename='stockreservation')
router.register(r'counts', InventoryCountViewSet, basename='inventorycount')
router.register(r'supplier-prices', SupplierPriceListViewSet, basename='supplierpricelist')

urlpatterns = [
    path('', include(router.urls)),
]