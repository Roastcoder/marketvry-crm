"""
URL patterns for horilla_activity API
"""

from rest_framework.routers import DefaultRouter

from horilla.urls import include, path
from horilla_activity.api.views import ActivityViewSet

router = DefaultRouter()
router.register(r"activities", ActivityViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
