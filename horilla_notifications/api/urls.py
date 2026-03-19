"""
URL configuration for horilla_notifications API
"""

from rest_framework.routers import DefaultRouter

from horilla.urls import include, path
from horilla_notifications.api.views import NotificationViewSet

router = DefaultRouter()
router.register(r"notifications", NotificationViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
