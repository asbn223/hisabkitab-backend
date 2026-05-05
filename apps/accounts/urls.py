# apps/accounts/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import AccountViewSet, TransactionViewSet, LedgerViewSet, FiscalYearViewSet

router = DefaultRouter()
router.register(r'accounts', AccountViewSet, basename='account')
router.register(r'transactions', TransactionViewSet, basename='transaction')
router.register(r'ledger', LedgerViewSet, basename='ledger')
router.register(r'fiscal-years', FiscalYearViewSet, basename='fiscalyear')

urlpatterns = [
    path('', include(router.urls)),
]