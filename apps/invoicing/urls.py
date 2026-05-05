from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CustomerViewSet, InvoiceViewSet, InvoicePaymentViewSet, CreditNoteViewSet

router = DefaultRouter()
router.register(r'customers', CustomerViewSet)
router.register(r'invoices', InvoiceViewSet)
router.register(r'payments', InvoicePaymentViewSet)
router.register(r'credit-notes', CreditNoteViewSet)

urlpatterns = [
    path('', include(router.urls)),
]