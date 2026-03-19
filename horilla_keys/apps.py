"""
AppLauncher for the horilla_keys app
"""

from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class HorillaKeysConfig(AppLauncher):
    """App configuration class for horilla_keys."""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_keys"
    verbose_name = _("Keyboard Shortcuts")

    js_files = "horilla_keys/assets/js/short_key.js"

    url_prefix = "shortkeys/"
    url_module = "horilla_keys.urls"
    url_namespace = "horilla_keys"

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
                "pattern": "keys/",
                "view_or_include": "horilla_keys.api.urls",
                "name": "horilla_keys_api",
                "namespace": "horilla_keys",
            }
        ]
