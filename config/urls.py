# config/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.decorators import api_view
from rest_framework.response import Response


@api_view(['GET'])
def health_check(request):
    """Health check endpoint for load balancers."""
    return Response({
        'status': 'healthy',
        'version': '1.0.0',
        'timestamp': __import__('datetime').datetime.now().isoformat(),
    })

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include([
        path('tenants/', include('apps.tenants.urls')),
        path('accounts/', include('apps.accounts.urls')),
        path('inventory/', include('apps.inventory.urls')),
        path('invoices/', include('apps.invoicing.urls')),
        path('purchases/', include('apps.purchases.urls')),
        path('payments/', include('apps.payments.urls')),
        path('tax/', include('apps.tax.urls')),
        path('reports/', include('apps.reports.urls')),
        # path('integrations/', include('apps.integrations.urls')),
    ])),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)