"""
AppLauncher for the horilla_automations app
"""

from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class HorillaAutomationsConfig(AppLauncher):
    """App configuration class for horilla_automations."""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_automations"
    verbose_name = _("Automations")

    url_prefix = "automations/"
    url_module = "horilla_automations.urls"
    url_namespace = "horilla_automations"

    auto_import_modules = [
        "registration",
        "menu",
        "signals",
    ]

    automation_files = ["load_automation/automation.json"]
