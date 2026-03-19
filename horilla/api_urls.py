# horilla/api_urls.py
"""
API URL configuration for the Horilla project,
including dynamic path collection and Swagger schema.
"""
# Standard library
import logging

# Third-party imports (Django)
from django.apps import apps
from django.urls import include, path

# Third-party imports (drf_yasg)
from drf_yasg import openapi
from drf_yasg.generators import OpenAPISchemaGenerator
from drf_yasg.inspectors import SwaggerAutoSchema
from drf_yasg.views import get_schema_view
from rest_framework import permissions

logger = logging.getLogger(__name__)


def collect_api_paths():
    """
    Dynamically collect API paths from all installed apps.

    This function scans all installed Django apps for a get_api_paths() method
    in their AppConfig class and collects the returned path patterns.

    Returns:
        list: A list of Django URL path objects for API endpoints

    Raises:
        Exception: Logs errors for apps with invalid path definitions
    """
    api_paths = []
    path_registry = {}  # Track paths to detect conflicts

    for app_config in apps.get_app_configs():
        try:
            # Check if the app has a get_api_paths method
            if hasattr(app_config, "get_api_paths"):
                app_paths = app_config.get_api_paths()

                if not isinstance(app_paths, list):
                    logger.error(
                        "App %s: get_api_paths() must return a list", app_config.name
                    )
                    continue

                for path_info in app_paths:
                    if not isinstance(path_info, dict):
                        logger.error(
                            "App %s: Each path must be a dictionary", app_config.name
                        )
                        continue

                    required_keys = {"pattern", "view_or_include"}
                    if not required_keys.issubset(path_info.keys()):
                        logger.error(
                            "App %s: Path missing required keys: %s",
                            app_config.name,
                            required_keys,
                        )
                        continue

                    pattern = path_info["pattern"]
                    view_or_include = path_info["view_or_include"]
                    name = path_info.get("name")
                    namespace = path_info.get("namespace", app_config.name)

                    # Normalize pattern to ensure single trailing slash
                    if not isinstance(pattern, str):
                        logger.error(
                            "App %s: 'pattern' must be a string", app_config.name
                        )
                        continue

                    normalized = pattern.strip("/") + "/"

                    # Check for path conflicts (relative to api/ mountpoint)
                    full_pattern = normalized
                    if full_pattern in path_registry:
                        logger.warning(
                            "Path conflict detected: 'api/%s' defined in both %s and %s",
                            full_pattern,
                            path_registry[full_pattern],
                            app_config.name,
                        )
                        continue

                    path_registry[full_pattern] = app_config.name

                    # Create the path object (mounted under /api/ via project urls)
                    if isinstance(view_or_include, str):
                        # It's an include string
                        api_path = path(
                            full_pattern, include(view_or_include), name=name
                        )
                    else:
                        # It's a view function/class
                        api_path = path(full_pattern, view_or_include, name=name)

                    api_paths.append(api_path)
                    logger.debug(
                        "Registered API path: api/%s from %s",
                        full_pattern,
                        app_config.name,
                    )

        except Exception as e:
            logger.error("Error collecting API paths from %s: %s", app_config.name, e)
            continue

    logger.info(
        "Collected %s API paths from %s apps", len(api_paths), len(path_registry)
    )
    return api_paths


def get_dynamic_api_patterns():
    """
    Get dynamically collected API patterns for schema generation.

    Returns:
        list: List of URL patterns for API documentation
    """
    try:
        return collect_api_paths()
    except Exception as e:
        logger.error("Failed to collect dynamic API patterns: %s", e)
        # Fallback to empty list to prevent schema generation failure
        return []


def get_app_verbose_name_from_view(view):
    """
    Get the verbose_name from the AppConfig for a given view.

    Args:
        view: The view class, function, or method

    Returns:
        str: The verbose_name from the app's AppConfig, or None if not found
    """
    try:
        # Get the view's module path
        module_path = None

        if hasattr(view, "__module__"):
            # Direct view class or function
            module_path = view.__module__
        elif hasattr(view, "view_class"):
            # For function-based views wrapped in viewsets
            module_path = view.view_class.__module__
        elif hasattr(view, "cls"):
            # For viewset actions/methods accessed through router
            module_path = view.cls.__module__
        elif hasattr(view, "__self__") and hasattr(view.__self__, "__class__"):
            # For bound methods (like viewset.list, viewset.create)
            module_path = view.__self__.__class__.__module__

        if not module_path:
            return None

        # Extract app name from module path
        # Examples:
        # 'horilla_activity.api.views' -> 'horilla_activity'
        parts = module_path.split(".")

        # Try to find matching app config by checking all installed apps
        # Match the longest possible app name prefix
        best_match = None
        best_match_length = 0

        for app_config in apps.get_app_configs():
            app_name = app_config.name
            # Check if the module path starts with the app name
            if module_path.startswith(app_name + "."):
                # Prefer longer matches (more specific app names)
                if len(app_name) > best_match_length:
                    best_match = app_config
                    best_match_length = len(app_name)

        if (
            best_match
            and hasattr(best_match, "verbose_name")
            and best_match.verbose_name
        ):
            return str(best_match.verbose_name)

    except Exception as e:
        logger.debug("Error getting app verbose_name for view %s: %s", view, e)

    return None


# Custom Auto Schema to use app verbose_name for tags
class VerboseNameAutoSchema(SwaggerAutoSchema):
    """
    Custom SwaggerAutoSchema that uses app verbose_name for tags instead of app name.
    """

    def get_tags(self, operation_keys=None):
        """
        Override to use app verbose_name for tags.
        """
        try:
            # Get the view to determine which app it belongs to
            view = getattr(self, "view", None)

            if view:
                # Get the verbose_name from the app config
                verbose_name = get_app_verbose_name_from_view(view)

                if verbose_name:
                    return [verbose_name]
        except Exception as e:
            logger.debug("Error getting verbose_name for tags: %s", e)

        # Fallback to default behavior if verbose_name not found
        return super().get_tags(operation_keys)


# Custom generator to force Swagger base path to '/api/' and remove Models tab
class ApiPrefixSchemaGenerator(OpenAPISchemaGenerator):
    """
    Custom OpenAPI schema generator that sets base path to '/api/' and removes Models tab.
    """

    def get_schema(self, request=None, public=False):
        schema = super().get_schema(request, public)
        # Ensure examples and "Request URL" use '/api/' as base path
        schema.base_path = "/api/"
        # Remove definitions to hide the Models tab
        # drf_yasg returns a Spec object with a _spec attribute containing the dict
        if hasattr(schema, "_spec") and isinstance(schema._spec, dict):
            schema._spec.pop("definitions", None)
            if "components" in schema._spec and isinstance(
                schema._spec["components"], dict
            ):
                schema._spec["components"].pop("schemas", None)
        # Also try direct attribute access
        elif hasattr(schema, "definitions"):
            schema.definitions = {}
        if hasattr(schema, "components") and hasattr(schema.components, "schemas"):
            schema.components.schemas = {}
        return schema


# Schema view for API documentation with dynamic pattern collection
# Get server URL from request in view instead of hardcoding
schema_view = get_schema_view(
    openapi.Info(
        title="HORILLA API",
        default_version="v1",
        description="API documentation for HORILLA system",
        terms_of_service="https://www.horilla.com/privacy-policy/",
        contact=openapi.Contact(email="support@horilla.com"),
        license=openapi.License(name="LGPL2.1 License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
    generator_class=ApiPrefixSchemaGenerator,
    patterns=get_dynamic_api_patterns(),
)


urlpatterns = [
    # API documentation with Swagger/OpenAPI
    path(
        "docs/",
        schema_view.with_ui("swagger", cache_timeout=0),
        name="schema-swagger-ui",
    ),
    path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="schema-redoc"),
] + collect_api_paths()  # Add dynamically collected API paths
