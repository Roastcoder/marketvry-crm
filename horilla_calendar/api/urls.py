"""
URL patterns for Horilla Calendar API
"""

from rest_framework.routers import DefaultRouter

from horilla.urls import include, path
from horilla_calendar.api.views import (
    UserAvailabilityViewSet,
    UserCalendarPreferenceViewSet,
)

router = DefaultRouter()
router.register(r"user-calendar-preferences", UserCalendarPreferenceViewSet)
router.register(r"user-availabilities", UserAvailabilityViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
