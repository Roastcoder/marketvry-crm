"""Leads app configuration."""

from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class LeadsConfig(AppLauncher):
    """Leads App Configuration"""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_crm.leads"
    verbose_name = _("Leads")

    url_prefix = "leads/"
    url_module = "horilla_crm.leads.urls"
    url_namespace = "leads"

    auto_import_modules = [
        "registration",
        "signals",
        "menu",
        "dashboard",
    ]

    celery_schedule_module = "celery_schedules"
    celery_schedule_variable = "HORILLA_CRM_BEAT_SCHEDULE"

    demo_data = {
        "files": [
            (4, "load_data/lead_stage.json"),
            (5, "load_data/leads.json"),
        ],
        "order": 2,
    }

    report_files = [
        "report_data/reports.json",
    ]

    def get_api_paths(self):
        """
        Return API path configurations for this app.

        Returns:
            list: List of dictionaries containing path configuration
        """
        return [
            {
                "pattern": "crm/leads/",
                "view_or_include": "horilla_crm.leads.api.urls",
                "name": "horilla_crm_leads_api",
                "namespace": "horilla_crm_leads",
            }
        ]
