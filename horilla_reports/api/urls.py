"""
URL patterns for horilla_reports API

This module mirrors the URL structure of other app APIs
using DefaultRouter for consistent endpoint patterns.
"""

from rest_framework.routers import DefaultRouter

from horilla.urls import include, path
from horilla_reports.api.views import ReportFolderViewSet, ReportViewSet

# Create router and register viewsets
router = DefaultRouter()
router.register(r"reports", ReportViewSet, basename="report")
router.register(r"report-folders", ReportFolderViewSet, basename="reportfolder")

urlpatterns = [
    path("", include(router.urls)),
]
