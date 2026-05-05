from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ReportViewSet, SavedReportViewSet, ReportExportViewSet

router = DefaultRouter()
router.register(r'reports', ReportViewSet, basename='reports')
router.register(r'saved', SavedReportViewSet)
router.register(r'exports', ReportExportViewSet)

urlpatterns = [
    path('', include(router.urls)),
]