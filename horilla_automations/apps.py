"""
AppConfig for the horilla_automations app
"""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class HorillaAutomationsConfig(AppConfig):
    """App configuration class for horilla_automations."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_automations"
    verbose_name = _("Automations")

    automation_files = ["load_automation/automation.json"]

    def ready(self):
        """Run app initialization logic (executed after Django setup).
        Used to auto-register URLs and connect signals if required.
        """
        try:
            # Auto-register this app's URLs and add to installed apps
            from django.urls import include, path

            from horilla.urls import urlpatterns

            # Add app URLs to main urlpatterns
            urlpatterns.append(
                path("automations/", include("horilla_automations.urls")),
            )

            __import__("horilla_automations.registration")
            __import__("horilla_automations.menu")
            __import__("horilla_automations.signals")

        except Exception as e:
            import logging

            logging.warning("HorillaAutomationsConfig.ready failed: %s", str(e))

        super().ready()
