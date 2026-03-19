"""View to handle load demo data"""

# Standard library imports
import json
import tempfile
from pathlib import Path

# Third-party imports (Django)
from django.conf import settings
from django.contrib import messages
from django.core.management import call_command
from django.db import connection, transaction
from django.utils import timezone
from django.views import View

# First-party / Horilla imports
from horilla.apps import apps
from horilla.auth.models import User
from horilla.http import JsonResponse, safe_url
from horilla.shortcuts import redirect, render
from horilla.utils.translation import gettext_lazy as _


def set_sqlite_foreign_keys(enabled: bool):
    """Enable or disable SQLite foreign key checks."""
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute(f"PRAGMA foreign_keys = {1 if enabled else 0};")


def inject_timestamps_into_fixture_data(data):
    """
    Inject current created_at and updated_at into fixture data so that
    every loaded record gets current timestamps (loaddata does not run
    model save(), so auto_now/auto_now_add are not applied).
    """
    if not isinstance(data, list):
        return data
    now = timezone.now().isoformat()
    for item in data:
        if isinstance(item, dict) and "fields" in item:
            fields = item["fields"]
            if "created_at" in fields:
                fields["created_at"] = now
            if "updated_at" in fields:
                fields["updated_at"] = now
    return data


class LoadDatabaseConditionView(View):
    """
    checks whether the database needs demo data.
    """

    def get_initialize_condition(self):
        """Check if database initialization is needed."""
        initialize_database = not User.objects.exists()
        return initialize_database


class LoadDatabase(View):
    """To load db init password"""

    def get(self, request, *args, **kwargs):
        """Handle GET requests for database initialization."""
        condition_view = LoadDatabaseConditionView()
        load_data = condition_view.get_initialize_condition()
        next_url = request.GET.get("next", "/")
        if load_data:
            return render(request, "load_data/init_password.html", {"next": next_url})

        next_url = safe_url(request, next_url)
        return redirect(next_url)


class ConfigureDemoData(View):
    """
    Handle configuration of demo data counts before loading.
    """

    # Default options and default value for all entities
    DEFAULT_OPTIONS = [500, 1000, 2000, 4000, 8000, 10000]
    DEFAULT_VALUE = 500

    def format_option_label(self, value):
        """Format option value for display"""
        if value >= 10000:
            return "10,000+"
        if value > 8000:
            return "Above 8,000"

        return f"{value:,}"

    def get_configurable_entities(self):
        """
        Collect all configurable entities from apps that define demo_data.
        Each entity includes: key, display_name, default, options, order, files.
        """
        entities = []

        for app_config in apps.get_app_configs():
            demo_data = getattr(app_config, "demo_data", None)
            if not demo_data:
                continue

            # Normalize to list of configs
            configs = demo_data if isinstance(demo_data, list) else [demo_data]

            for cfg in configs:
                options_raw = cfg.get("options", self.DEFAULT_OPTIONS)
                default_value = cfg.get("default", options_raw[0])

                key = cfg.get("key") or (
                    str(app_config.verbose_name).lower().replace(" ", "_") + "_count"
                )

                entities.append(
                    {
                        "key": key,
                        "display_name": cfg.get(
                            "display_name", str(app_config.verbose_name)
                        ),
                        "default": default_value,
                        "options": [
                            {"value": opt, "label": self.format_option_label(opt)}
                            for opt in options_raw
                        ],
                        "order": cfg.get("order", 999),
                        "files": cfg.get("files", []),
                    }
                )

        return sorted(entities, key=lambda x: x["order"])

    def get(self, request, *args, **kwargs):
        """Display configuration page"""
        if request.session.get("init_password") != settings.DB_INIT_PASSWORD:
            return redirect("horilla_core:load_data")

        entities = self.get_configurable_entities()
        return render(request, "load_data/configure_data.html", {"entities": entities})

    def post(self, request, *args, **kwargs):
        """Save configuration and proceed to loading"""
        if request.session.get("init_password") != settings.DB_INIT_PASSWORD:
            messages.error(request, _("Unauthorized. Please authenticate first."))
            return redirect("horilla_core:load_data")

        data_config = {}
        entities = self.get_configurable_entities()

        for entity in entities:
            key = entity["key"]
            value = request.POST.get(key, entity["default"])
            data_config[key] = int(value)

        request.session["data_config"] = data_config

        load_demo = LoadDemoDatabase()
        data_files = load_demo.get_data_files()

        context = {
            "total_files": len(data_files),
            "data_files": [Path(f).name for f in data_files],
            "data_config": data_config,
        }
        return render(request, "load_data/loading.html", context)


class LoadDemoDatabase(View):
    """
    Loads demo database with progress tracking.
    Supports dynamic demo data files from apps with ordering.
    """

    def get_data_files(self):
        """Collect all demo data files from installed apps in order."""
        data_files = []

        for app_config in apps.get_app_configs():
            demo_data = getattr(app_config, "demo_data", None)
            if not demo_data:
                continue

            app_path = Path(app_config.path)

            for order, relative_file in demo_data.get("files", []):
                file_path = app_path / relative_file
                if file_path.exists():
                    data_files.append((order, str(file_path)))

        return [fpath for _, fpath in sorted(data_files, key=lambda x: x[0])]

    def get_file_limit_key(self, filename):
        """
        Determine the limit key for a given data file based on its app config.
        """
        filename = Path(filename).name

        for app_config in apps.get_app_configs():
            demo_data = getattr(app_config, "demo_data", None)
            if not demo_data:
                continue

            _app_path = Path(app_config.path)
            configs = demo_data if isinstance(demo_data, list) else [demo_data]

            for cfg in configs:
                # Build list of filenames only once
                cfg_files = [Path(f[1]).name for f in cfg.get("files", [])]

                if filename in cfg_files:
                    return cfg.get(
                        "key",
                        str(app_config.verbose_name).lower().replace(" ", "_")
                        + "_count",
                    )

        return None

    def get_model_limit(self, filename, data_config):
        """
        Get the limit for number of records to load based on file type.
        Returns None if no limit should be applied.
        """
        limit_key = self.get_file_limit_key(filename)

        if limit_key and limit_key in data_config:
            return data_config[limit_key]

        return None

    def load_limited_data(self, filename, limit=None):
        """
        Load data from JSON file with optional limit on number of records.
        Injects current created_at and updated_at into all fixture objects
        so that loaded records have up-to-date timestamps.
        """
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            call_command("loaddata", str(filename))
            return

        data_to_load = data[:limit] if limit is not None else data
        inject_timestamps_into_fixture_data(data_to_load)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp_file:
            json.dump(data_to_load, tmp_file, ensure_ascii=False, indent=2)
            tmp_filename = tmp_file.name

        try:
            call_command("loaddata", tmp_filename)
        finally:
            Path(tmp_filename).unlink(missing_ok=True)

    def post(self, request, *args, **kwargs):
        """Handle password authentication and redirect to configuration."""
        condition_view = LoadDatabaseConditionView()
        load_data = condition_view.get_initialize_condition()

        if not load_data:
            messages.error(request, _("Database already initialized"))
            return redirect("/")

        password = request.POST.get("init_password", "")
        if password != settings.DB_INIT_PASSWORD:
            return render(
                request,
                "load_data/init_password.html",
                {"error": _("Invalid password. Please try again.")},
            )

        request.session["init_password"] = password

        return redirect("horilla_core:configure_demo_data")

    def get(self, request, *args, **kwargs):
        """Handle AJAX requests for file loading progress."""
        if "file_index" in request.GET:
            if request.session.get("init_password") != settings.DB_INIT_PASSWORD:
                return JsonResponse(
                    {
                        "status": "error",
                        "message": _("Unauthorized. Please authenticate first."),
                    },
                    status=401,
                )
            return self.load_file_ajax(request)

        condition_view = LoadDatabaseConditionView()
        load_data = condition_view.get_initialize_condition()
        next_url = request.GET.get("next", "/")

        if load_data:
            if request.session.get("init_password") == settings.DB_INIT_PASSWORD:
                return redirect("horilla_core:configure_demo_data")

            return render(request, "load_data/init_password.html")

        next_url = safe_url(request, next_url)
        return redirect(next_url)

    def load_file_ajax(self, request):
        """Load individual data file via AJAX."""
        file_index = int(request.GET.get("file_index", 0))
        data_files = self.get_data_files()
        data_config = request.session.get("data_config", {})

        if file_index >= len(data_files):
            request.session.pop("init_password", None)
            request.session.pop("data_config", None)
            messages.success(
                request,
                _(
                    "Demo database loaded successfully! You can now login with username 'admin' and password 'admin'."
                ),
            )
            return JsonResponse(
                {
                    "status": "complete",
                    "message": _("Database loaded successfully."),
                    "redirect": "/",
                }
            )

        filename = data_files[file_index]

        limit = self.get_model_limit(filename, data_config)

        try:
            if not Path(filename).exists():
                return JsonResponse(
                    {
                        "status": "error",
                        "message": _("Data file not found: {}").format(
                            Path(filename).name
                        ),
                        "file": Path(filename).name,
                    }
                )

            set_sqlite_foreign_keys(False)
            try:
                with transaction.atomic():
                    self.load_limited_data(filename, limit)
            finally:
                set_sqlite_foreign_keys(True)

            progress = ((file_index + 1) / len(data_files)) * 100

            original_name = Path(filename).name

            display_name = original_name
            if limit:
                display_name = f"{original_name}"

            response_data = {
                "status": "success",
                "file": original_name,
                "display_name": display_name,
                "progress": round(progress, 2),
                "current": file_index + 1,
                "total": len(data_files),
                "message": _("Loading {}").format(display_name),
            }

            return JsonResponse(response_data)

        except Exception as e:
            call_command("flush", "--no-input")
            return JsonResponse(
                {
                    "status": "error",
                    "message": _(
                        "Error loading {}. All changes have been rolled back."
                    ).format(Path(filename).name),
                    "error": str(e),
                    "file": Path(filename).name,
                }
            )
