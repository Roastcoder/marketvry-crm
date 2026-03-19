"""App configuration for dashboard app."""

from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class HorillaDashboardConfig(AppLauncher):
    """
    HorillaDashboardConfig App Configuration
    """

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_dashboard"
    verbose_name = _("Dashboard")

    url_prefix = "dashboard/"
    url_module = "horilla_dashboard.urls"
    url_namespace = "horilla_dashboard"

    auto_import_modules = [
        "registration",
        "signals",
        "menu",
    ]

    # Define API paths for this app
    def get_api_paths(self):
        """
        Return API path configurations for this app.

        Returns:
            list: List of dictionaries containing path configuration
        """
        return [
            {
                "pattern": "/dashboard/",
                "view_or_include": "horilla_dashboard.api.urls",
                "name": "horilla_dashboard_api",
                "namespace": "horilla_dashboard",
            }
        ]
