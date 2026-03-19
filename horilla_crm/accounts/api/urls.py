"""
URL patterns for horilla_crm.accounts API
"""

from rest_framework.routers import DefaultRouter

from horilla.urls import include, path
from horilla_crm.accounts.api.views import (
    AccountViewSet,
    PartnerAccountRelationshipViewSet,
)

router = DefaultRouter()
router.register(r"accounts", AccountViewSet)
router.register(r"partner-account-relationships", PartnerAccountRelationshipViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
