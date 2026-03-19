"""Django app configuration for the Horilla mail system."""

from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _


class HorillaMailConfig(AppLauncher):
    """App configuration class for the Horilla mail system."""

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla_mail"
    verbose_name = _("Mail System")

    template_files = [
        "load_template/template.json",
    ]

    url_prefix = "mail/"
    url_module = "horilla_mail.urls"
    url_namespace = "horilla_mail"

    auto_import_modules = [
        "registration",
        "signals",
        "scheduler",
        "menu",
    ]

    celery_schedule_module = "celery_schedules"

    def get_api_paths(self):
        """
        Return API path configurations for this app.

        Returns:
            list: List of dictionaries containing path configuration
        """
        return [
            {
                "pattern": "mail/",
                "view_or_include": "horilla_mail.api.urls",
                "name": "horilla_mail_api",
                "namespace": "horilla_mail",
            }
        ]
