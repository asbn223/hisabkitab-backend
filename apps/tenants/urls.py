# apps/tenants/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import TenantViewSet, TenantUserViewSet

router = DefaultRouter()
router.register(r'', TenantViewSet, basename='tenant')
router.register(r'users', TenantUserViewSet, basename='tenantuser')

urlpatterns = [
    path('', include(router.urls)),
]