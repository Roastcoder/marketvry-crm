"""
URL patterns for horilla_crm.contacts API
"""

from rest_framework.routers import DefaultRouter

from horilla.urls import include, path
from horilla_crm.contacts.api.views import ContactViewSet

router = DefaultRouter()
router.register(r"contacts", ContactViewSet)

urlpatterns = [
    path("", include(router.urls)),
]
