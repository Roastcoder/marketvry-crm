"""
URL configuration for horilla_crm.leads API

This module mirrors the URL structure of horilla_crm.accounts API
using DefaultRouter for consistent endpoint patterns.
"""

from rest_framework.routers import DefaultRouter

from horilla.urls import include, path
from horilla_crm.leads.api.views import (
    LeadStatusViewSet,
    LeadViewSet,
    ScoringCriterionViewSet,
    ScoringRuleViewSet,
)

# Create router and register viewsets
router = DefaultRouter()
router.register(r"leads", LeadViewSet, basename="lead")
router.register(r"lead-statuses", LeadStatusViewSet, basename="leadstatus")
router.register(r"scoring-rules", ScoringRuleViewSet)
router.register(r"scoring-criteria", ScoringCriterionViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
