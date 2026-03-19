"""
URL patterns for horilla_crm.opportunities API
"""

from rest_framework.routers import DefaultRouter

from horilla.urls import include, path
from horilla_crm.opportunities.api.views import (
    DefaultOpportunityMemberViewSet,
    OpportunityStageViewSet,
    OpportunityTeamMemberViewSet,
    OpportunityTeamViewSet,
    OpportunityViewSet,
)

router = DefaultRouter()
router.register(r"opportunities", OpportunityViewSet)
router.register(r"opportunity-stages", OpportunityStageViewSet)
router.register(r"opportunity-teams", OpportunityTeamViewSet)
router.register(r"opportunity-team-members", OpportunityTeamMemberViewSet)
router.register(r"default-opportunity-members", DefaultOpportunityMemberViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
