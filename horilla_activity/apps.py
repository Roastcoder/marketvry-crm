"""App configuration for the activity module."""

from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class HorillaActivityConfig(AppLauncher):
    """
    Configuration class for the Activity app in Horilla.
    """

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_activity"
    verbose_name = _("Activity")

    url_prefix = "activity/"
    url_module = "horilla_activity.urls"
    url_namespace = "horilla_activity"

    auto_import_modules = [
        "registration",
        "methods",
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
                "pattern": "/activity/",
                "view_or_include": "horilla_activity.api.urls",
                "name": "horilla_activity_api",
                "namespace": "horilla_activity",
            }
        ]
