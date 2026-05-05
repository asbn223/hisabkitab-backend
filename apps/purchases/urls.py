from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SupplierViewSet, PurchaseRequisitionViewSet, PurchaseOrderViewSet,
    GoodsReceiptNoteViewSet, SupplierBillViewSet, SupplierPaymentViewSet
)

router = DefaultRouter()
router.register(r'suppliers', SupplierViewSet)
router.register(r'requisitions', PurchaseRequisitionViewSet)
router.register(r'purchase-orders', PurchaseOrderViewSet)
router.register(r'grns', GoodsReceiptNoteViewSet)
router.register(r'supplier-bills', SupplierBillViewSet)
router.register(r'supplier-payments', SupplierPaymentViewSet)

urlpatterns = [
    path('', include(router.urls)),
]