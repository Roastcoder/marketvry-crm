"""
Horilla apps - re-exports django.apps for consistent imports.

Use: from horilla.apps import apps, AppConfig
"""

import importlib
import logging
from django.apps import AppConfig, apps
from django.conf import settings
from django.urls import include, path

__all__ = ["AppConfig", "apps", "AppLauncher"]


class AppLauncher(AppConfig):
    """
    Module AppLauncher for all Horilla apps.

    Provides:
    - Auto URL registration
    - Auto module importing (registration, signals, menu, etc.)
    - API path definition support
    - Celery schedule auto-merge
    - Safe exception handling
    """

    # ===== Optional Configurations (Override in child) =====
    url_prefix = None  # e.g. "dashboard/"
    url_module = None  # e.g. "horilla_dashboard.urls"
    url_namespace = None  # Optional namespace

    js_files = None  # str or list of static paths, e.g. "app_name/assets/js/file.js"

    auto_import_modules = []  # ["registration", "signals", "menu"]

    celery_schedule_module = None  # e.g. "celery_schedules"
    celery_schedule_variable = "HORILLA_BEAT_SCHEDULE"

    # ========================================================

    def get_api_paths(self):
        """
        Override in child if needed.
        """
        return []

    # ================= Core Logic =================

    def ready(self):
        try:
            self._register_urls()
            self._register_js()
            self._auto_import_modules()
            self._register_celery_schedule()

        except Exception as e:
            logging.warning("%s.ready failed: %s", self.__class__.__name__, e)

        super().ready()

    # ================= Internal Helpers =================

    def _register_urls(self):
        """
        Auto-register app URLs to the ROOT_URLCONF dynamically.
        """
        if self.url_module is None or self.url_prefix is None:
            return

        # Dynamically load the root urlconf module
        urlconf = importlib.import_module(settings.ROOT_URLCONF)

        # Get existing urlpatterns
        urlpatterns = getattr(urlconf, "urlpatterns", None)

        if urlpatterns is None:
            return

        if self.url_namespace:
            urlpatterns.append(
                path(
                    self.url_prefix,
                    include((self.url_module, self.url_namespace)),
                )
            )
        else:
            urlpatterns.append(
                path(
                    self.url_prefix,
                    include(self.url_module),
                )
            )

    def _register_js(self):
        """
        Register this app's JS files with the asset registry if js_files is set.
        """
        if self.js_files is None:
            return
        from horilla.registry.asset_registry import register_js

        register_js(self.js_files)

    def _auto_import_modules(self):
        """
        Auto import modules like:
        registration, signals, menu, dashboard, scheduler
        """
        for module in self.auto_import_modules:
            try:
                importlib.import_module(f"{self.name}.{module}")
            except ModuleNotFoundError:
                logging.warning(
                    "Optional module '%s' not found for app '%s'.",
                    module,
                    self.name,
                )

    def _register_celery_schedule(self):
        """
        Merge celery beat schedule if defined
        """
        if not self.celery_schedule_module:
            return

        try:
            module = importlib.import_module(
                f"{self.name}.{self.celery_schedule_module}"
            )
            schedule = getattr(
                module,
                self.celery_schedule_variable,
                None,
            )

            if schedule:
                if not hasattr(settings, "CELERY_BEAT_SCHEDULE"):
                    settings.CELERY_BEAT_SCHEDULE = {}

                settings.CELERY_BEAT_SCHEDULE.update(schedule)

        except ModuleNotFoundError:
            pass
