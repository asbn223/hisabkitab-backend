from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PaymentGatewayViewSet, PaymentTransactionViewSet,
    BankAccountViewSet, BankStatementViewSet, BankStatementLineViewSet,
    esewa_callback, khalti_callback
)

router = DefaultRouter()
router.register(r'gateways', PaymentGatewayViewSet)
router.register(r'transactions', PaymentTransactionViewSet)
router.register(r'bank-accounts', BankAccountViewSet)
router.register(r'bank-statements', BankStatementViewSet)
router.register(r'statement-lines', BankStatementLineViewSet)

urlpatterns = [
    path('', include(router.urls)),
    # Callback URLs (public)
    path('callback/esewa/<str:status>/', esewa_callback, name='esewa-callback'),
    path('callback/khalti/<str:status>/', khalti_callback, name='khalti-callback'),
]