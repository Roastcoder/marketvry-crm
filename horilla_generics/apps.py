"""
Horilla generics app configuration.

This module defines the AppLauncher for the horilla_generics application and performs
application startup tasks such as URL registration and signal imports.
"""

from horilla.apps import AppLauncher


class HorillaGenericsConfig(AppLauncher):
    """App configuration for horilla_generics application."""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_generics"

    url_prefix = "generics/"
    url_module = "horilla_generics.urls"
    url_namespace = "horilla_generics"

    auto_import_modules = ["signals"]
