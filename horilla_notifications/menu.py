"""
This module registers Floating, Settings, My Settings, and Main Section menus
for the Horilla CRM Notifications app
"""

from horilla.menu import settings_menu

# First party / Horilla imports
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _
from horilla_notifications.models import NotificationTemplate


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
            "perm": "horilla_notifications.view_notificationtemplate",
        },
    ]
