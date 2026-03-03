"""
App configuration for the Reports module in Horilla.
Handles app metadata and auto-registering URLs.
"""

from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class HorillaReportsConfig(AppLauncher):
    """
    App configuration class for the Reports module in Horilla.
    """

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_reports"
    verbose_name = _("Reports")

    url_prefix = "reports/"
    url_module = "horilla_reports.urls"
    url_namespace = "horilla_reports"

    auto_import_modules = [
        "registration",
        "signals",
        "menu",
    ]

    def get_api_paths(self):
        """
        Return API path configurations for this app.

        Returns:
            list: List of dictionaries containing path configuration
        """
        return [
            {
                "pattern": "reports/",
                "view_or_include": "horilla_reports.api.urls",
                "name": "horilla_reports_api",
                "namespace": "horilla_reports",
            }
        ]
