"""
This module registers Floating, Settings, My Settings, and Main Section menus
for the Horilla CRM Notifications app
"""

from django.urls import reverse_lazy

from horilla.menu import settings_menu
from horilla_notifications.models import NotificationTemplate
from django.utils.translation import gettext_lazy as _



@settings_menu.register
class NotificationSettings:
    """Settings menu for Notification module"""

    title = _("Notifications")
    icon = "/assets/icons/notification.svg"
    order = 4
    items = [
        {
            "label": NotificationTemplate()._meta.verbose_name,
            "url": reverse_lazy("horilla_notifications:notification_template_view"),
            "hx-target": "#settings-content",
            "hx-push-url": "true",
            "hx-select": "#notification-template-view",
            "hx-select-oob": "#settings-sidebar",
        },
    ]

