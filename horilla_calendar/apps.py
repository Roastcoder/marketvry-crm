"""Configuration for the calendar app in Horilla."""

from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class HorillaCalendarConfig(AppLauncher):
    """App configuration class for the Horilla Calendar app."""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_calendar"
    verbose_name = _("Calendar")

    url_prefix = "calendar/"
    url_module = "horilla_calendar.urls"
    url_namespace = "horilla_calendar"

    auto_import_modules = [
        "menu",
        "signals",
    ]

    def get_api_paths(self):
        """
        Return API path configurations for this app.

        Returns:
            list: List of dictionaries containing path configuration
        """
        return [
            {
                "pattern": "/calendar/",
                "view_or_include": "horilla_calendar.api.urls",
                "name": "horilla_calendar_api",
                "namespace": "horilla_calendar",
            }
        ]
