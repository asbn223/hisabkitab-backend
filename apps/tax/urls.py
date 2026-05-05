from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    TaxConfigViewSet, TaxPeriodViewSet, VATReturnViewSet,
    VATTransactionViewSet, TDSSectionViewSet, TDSDeductionViewSet,
    TDSReturnViewSet, TaxDepositViewSet, TaxCertificateViewSet
)

router = DefaultRouter()
router.register(r'config', TaxConfigViewSet)
router.register(r'periods', TaxPeriodViewSet)
router.register(r'vat-returns', VATReturnViewSet)
router.register(r'vat-transactions', VATTransactionViewSet)
router.register(r'tds-sections', TDSSectionViewSet)
router.register(r'tds-deductions', TDSDeductionViewSet)
router.register(r'tds-returns', TDSReturnViewSet)
router.register(r'deposits', TaxDepositViewSet)
router.register(r'certificates', TaxCertificateViewSet)

urlpatterns = [
    path('', include(router.urls)),
]