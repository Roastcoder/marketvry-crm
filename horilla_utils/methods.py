"""
Utility methods for the Horilla application.

This module contains helper functions that provide additional
functionality for working with models and other components in the
Horilla application.
"""

# Standard library
import logging
import re

from django import template
from django.middleware.csrf import get_token
from django.template import loader
from django.template.defaultfilters import register
from django.utils.functional import lazy
from django.utils.html import format_html

# Django / third-party imports
from django.utils.safestring import SafeString

from horilla import settings

# First-party (Horilla) imports
from horilla.apps import apps
from horilla.menu.sub_section_menu import sub_section_menu as menu_registry
from horilla_core.models import HorillaContentType
from horilla_utils.middlewares import _thread_local

logger = logging.getLogger(__name__)


def get_horilla_model_class(app_label, model):
    """
    Retrieves the model class for the given app label and model
    name using Django's HorillaContentType framework.
    Args:
        app_label (str): The label of the application where the model is defined.
        model (str): The name of the model to retrieve.

    Returns:
        Model: The Django model class corresponding to the specified app label and model name.

    """
    content_type = HorillaContentType.objects.get(app_label=app_label, model=model)
    model_class = content_type.model_class()
    return model_class


def csrf_input(request):
    """Return an HTML snippet for the CSRF hidden input for the given request."""
    return format_html(
        '<input type="hidden" name="csrfmiddlewaretoken" value="{}">',
        get_token(request),
    )


@register.simple_tag(takes_context=True)
def csrf_token(context):
    """Access CSRF token inside the render_template method.

    Falls back to thread-local request if context does not contain a request.
    """
    try:
        request = context["request"]
    except Exception:
        request = getattr(_thread_local, "request")
    csrf_input_lazy = lazy(csrf_input, SafeString, str)
    return csrf_input_lazy(request)


def get_all_context_variables(request) -> dict:
    """
    This method will return dictionary format of context processors
    """
    if getattr(request, "all_context_variables", None) is None:
        all_context_variables = {}
        for processor_path in settings.TEMPLATES[0]["OPTIONS"]["context_processors"]:
            module_path, func_name = processor_path.rsplit(".", 1)
            module = __import__(module_path, fromlist=[func_name])
            func = getattr(module, func_name)
            context = func(request)
            all_context_variables.update(context)
        all_context_variables["csrf_token"] = csrf_token(all_context_variables)
        request.all_context_variables = all_context_variables
    return request.all_context_variables


def render_template(
    path: str,
    context: dict,
    decoding: str = "utf-8",
    status: int = None,
    _using=None,
) -> str:
    """
    This method is used to render HTML text with context.
    """
    request = getattr(_thread_local, "request", None)
    context.update(get_all_context_variables(request))
    template_loader = loader.get_template(path)
    template_body = template_loader.template.source
    template_bdy = template.Template(template_body)
    context_instance = template.Context(context)
    rendered_content = template_bdy.render(context_instance)
    return format_html("{}", rendered_content)


def closest_numbers(numbers: list, input_number: int) -> tuple:
    """
    This method is used to find previous and next of numbers
    """
    previous_number = input_number
    next_number = input_number
    try:
        index = numbers.index(input_number)
        if index > 0:
            previous_number = numbers[index - 1]
        else:
            previous_number = numbers[-1]
        if index + 1 == len(numbers):
            next_number = numbers[0]
        elif index < len(numbers):
            next_number = numbers[index + 1]
        else:
            next_number = numbers[0]
    except ValueError:
        # input_number not found in numbers; return defaults
        pass
    return (previous_number, next_number)


def get_section_info_for_model(model_input):
    """Fetch section and URL for a model's app from registered sub-section menus.

    Args:
        model_input: Either a model class or a string in
        format 'app_label.ModelName' or just 'ModelName'
    """

    # Convert string to model class if needed
    if isinstance(model_input, str):
        try:
            # Check if it's in 'app_label.ModelName' format
            if "." in model_input:
                model_class = apps.get_model(model_input)
            else:
                # If just model name, search across all apps
                model_class = None
                for app_config in apps.get_app_configs():
                    try:
                        model_class = app_config.get_model(model_input)
                        break
                    except LookupError:
                        continue

                if model_class is None:
                    logger.warning("Could not find model '%s' in any app", model_input)
                    return {"section": "", "url": "#"}

        except (LookupError, ValueError) as e:
            logger.warning("Could not get model from string '%s': %s", model_input, e)
            return {"section": "", "url": "#"}
    else:
        model_class = model_input

    # Now we always have a model class
    try:
        app_label = model_class._meta.app_label
    except AttributeError:
        logger.warning("Invalid model_input type: %s", type(model_input))
        return {"section": "", "url": "#"}

    try:
        if not isinstance(menu_registry, list):
            logger.warning("sub_section_menu is not a list: %s", type(menu_registry))
            return {"section": "", "url": "#"}

        for menu_cls in menu_registry:
            if hasattr(menu_cls, "app_label"):
                cls_app_label = getattr(menu_cls, "app_label", None)

                if cls_app_label == app_label:
                    return {
                        "section": getattr(menu_cls, "section", ""),
                        "url": str(getattr(menu_cls, "url", "")),
                    }

    except Exception as e:
        logger.warning("Error in get_section_info_for_model: %s", e)

    return {"section": "", "url": "#"}


def has_xss(value: str) -> bool:
    """
    Detect common XSS (Cross-Site Scripting) attempts in a string.

    This function checks for various XSS patterns including:
    - Script tags (<script>...</script>)
    - JavaScript pseudo-protocol (javascript:)
    - Inline event handlers (onclick, onload, etc.)
    - Dangerous active content (embed, object, iframe, svg, etc.)
    - JS API abuse patterns

    Args:
        value (str): The string to check for XSS patterns.

    Returns:
        bool: True if XSS patterns are detected, False otherwise.

    Example:
        >>> has_xss("<script>alert('XSS')</script>")
        True
        >>> has_xss("Hello world")
        False
        >>> has_xss("javascript:alert('XSS')")
        True
    """
    if not isinstance(value, str):
        return False

    xss_patterns = [
        # <script> ... </script> with any attributes
        r"<\s*script[^>]*>.*?<\s*/\s*script\s*>",
        # Opening <script> tag (for incomplete scripts)
        r"<\s*script[^>]*>",
        r"javascript\s*:",  # javascript: pseudo-protocol
        r"on\w+\s*=",  # inline event handlers (onclick, onload, etc.)
        # dangerous active content
        r"<\s*(embed|object|iframe|svg|math|link|meta).*?>",
        # JS API abuse
        r"on\w+\s*=\s*['\"]?\s*(eval|setTimeout|setInterval|new\s+Function|XMLHttpRequest|fetch|\$\s*\()[^>]*",
    ]

    combined = re.compile("|".join(xss_patterns), re.IGNORECASE | re.DOTALL)
    result = bool(combined.search(value))
    return result
