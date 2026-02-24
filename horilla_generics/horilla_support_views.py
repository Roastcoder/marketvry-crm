"""
Support views for horilla_generics.

This module provides various small helper views used by the horilla_generics app
such as field editing, list management, pinning views, and select2 helpers.
"""

# Standard library
import importlib
import inspect
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode, urlparse

# Third-party
import pytz
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import IntegrityError, models
from django.db.models import CharField, Q, TextField
from django.db.models.fields import Field
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.decorators import method_decorator
from django.utils.encoding import force_str
from django.utils.html import escape
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import FormView

from horilla.exceptions import HorillaHttp404
from horilla.utils.choices import FIELD_TYPE_MAP

# First-party (Horilla)
from horilla.utils.shortcuts import get_object_or_404
from horilla_core.decorators import htmx_required
from horilla_core.models import (
    DetailFieldVisibility,
    HorillaContentType,
    KanbanGroupBy,
    ListColumnVisibility,
    PinnedView,
)
from horilla_core.utils import filter_hidden_fields
from horilla_generics.methods import get_dynamic_form_for_model
from horilla_generics.views import (
    HorillaDetailView,
    HorillaGroupByView,
    HorillaKanbanView,
)

# Local imports
from .forms import ColumnSelectionForm, KanbanGroupByForm, SaveFilterListForm

logger = logging.getLogger(__name__)

# Condition form: operator values (from horilla.utils.choices) allowed per field type.
# Mirrors filter operator logic so conditions use operators matching the field type.
CONDITION_OPERATORS_BY_FIELD_TYPE = {
    "boolean": ["equals", "not_equals"],
    "text": [
        "equals",
        "not_equals",
        "contains",
        "not_contains",
        "starts_with",
        "ends_with",
        "is_empty",
        "is_not_empty",
    ],
    "number": [
        "equals",
        "not_equals",
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "is_empty",
        "is_not_empty",
    ],
    "float": [
        "equals",
        "not_equals",
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "is_empty",
        "is_not_empty",
    ],
    "decimal": [
        "equals",
        "not_equals",
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "is_empty",
        "is_not_empty",
    ],
    "date": [
        "equals",
        "not_equals",
        "greater_than",
        "less_than",
        "is_empty",
        "is_not_empty",
    ],
    "datetime": [
        "equals",
        "not_equals",
        "greater_than",
        "less_than",
        "is_empty",
        "is_not_empty",
    ],
    "foreignkey": ["equals", "not_equals", "is_empty", "is_not_empty"],
    "choice": ["equals", "not_equals", "is_empty", "is_not_empty"],
    "other": ["equals", "not_equals", "contains", "is_empty", "is_not_empty"],
}


def _ensure_json_serializable(fields_list):
    """Convert all values to plain str for JSON serialization (avoids lazy __proxy__)."""
    return [[str(v), str(n)] for v, n in fields_list]


def get_detail_field_defaults_no_request(model):
    """
    Get default header_fields and details_fields without request (for signals).
    When request is None, section view resolution may fall back to model fields.
    """
    return _get_detail_field_defaults(model, None)


def _get_detail_field_defaults(model, request):
    """Get default header_fields and details_fields for a model's detail view."""
    default_header = []
    default_details = []

    detail_view_class = HorillaDetailView._view_registry.get(model)
    if detail_view_class:
        # Use view's effective excluded fields (base_excluded_fields + excluded_fields)
        base = getattr(detail_view_class, "base_excluded_fields", None)
        extra = getattr(detail_view_class, "excluded_fields", [])
        if base is not None:
            excluded = set(base) | set(extra or [])
        else:
            excluded = (
                set(extra)
                if extra
                else {
                    "id",
                    "created_at",
                    "updated_at",
                    "history",
                    "is_active",
                    "additional_info",
                }
            )
        # Automatically exclude pipeline_field from header and details
        pf = getattr(detail_view_class, "pipeline_field", None)
        if pf:
            excluded = excluded | {str(pf)}
        body = getattr(detail_view_class, "body", [])
        try:
            default_header = [
                [force_str(model._meta.get_field(f).verbose_name), str(f)]
                for f in body
                if f not in excluded
            ]
        except Exception:
            default_header = []
        details_url = getattr(detail_view_class, "details_section_url_name", None)
        if not details_url and request:
            details_url = request.GET.get("details_section_url") or None
        if details_url:
            try:
                from django.urls import resolve, reverse

                resolved = resolve(reverse(details_url, kwargs={"pk": 1}))
                section_view = getattr(resolved.func, "view_class", None)
                if section_view:
                    view_inst = section_view()
                    view_inst.request = request
                    view_inst.model = model
                    raw_details = view_inst.get_default_body()
                    default_details = _ensure_json_serializable(raw_details)
                    # Automatically exclude pipeline_field (section view may not have it in GET)
                    if pf and default_details:
                        default_details = [
                            f
                            for f in default_details
                            if (
                                f[1]
                                if isinstance(f, (list, tuple)) and len(f) >= 2
                                else f
                            )
                            != str(pf)
                        ]
                else:
                    raise ValueError("No section view")
            except Exception:
                default_details = [
                    [force_str(f.verbose_name), str(f.name)]
                    for f in model._meta.get_fields()
                    if isinstance(f, Field)
                    and f.name not in excluded
                    and hasattr(f, "verbose_name")
                ]
        else:
            # Use detail view's effective excluded (already base + child excluded_fields); pipeline_field already in excluded
            default_details = [
                [force_str(f.verbose_name), str(f.name)]
                for f in model._meta.get_fields()
                if isinstance(f, Field)
                and f.name not in excluded
                and hasattr(f, "verbose_name")
            ]
    else:
        # No registered detail view; use HorillaDetailView base_excluded_fields
        excluded = set(HorillaDetailView.base_excluded_fields)
        default_header = default_details = [
            [force_str(f.verbose_name), str(f.name)]
            for f in model._meta.get_fields()
            if isinstance(f, Field)
            and f.name not in excluded
            and hasattr(f, "verbose_name")
        ]
    default_header = _ensure_json_serializable(default_header)
    return default_header, default_details


def get_default_columns_from_view(url_name, app_label, model_name, request):
    """
    Get default columns from the view class based on URL name.

    Args:
        url_name: The URL name
        app_label: The app label
        model_name: The model name
        request: The request object (for getting URL resolver)

    Returns:
        List of default column field names, or None if view cannot be resolved
    """
    try:
        from django.urls import get_resolver

        from horilla_generics.views import HorillaListView

        # Get the URL resolver
        resolver = get_resolver()
        view_func = None

        # Try to find the URL pattern by name
        # URL name might be in format 'app:name' or just 'name'
        if ":" in url_name:
            app_name, pattern_name = url_name.split(":", 1)
        else:
            pattern_name = url_name
            app_name = None

        def find_pattern_by_name(patterns, target_name, target_app=None):
            """Recursively search for URL pattern by name"""
            for pattern in patterns:
                # Check if this pattern matches
                pattern_app = getattr(pattern, "app_name", None)
                pattern_name_attr = getattr(pattern, "name", None)

                if pattern_name_attr == target_name:
                    if target_app is None or pattern_app == target_app:
                        return getattr(pattern, "callback", None)

                # Recursively search nested patterns
                if hasattr(pattern, "url_patterns"):
                    result = find_pattern_by_name(
                        pattern.url_patterns, target_name, target_app
                    )
                    if result:
                        return result
            return None

        view_func = find_pattern_by_name(resolver.url_patterns, pattern_name, app_name)

        if not view_func:
            return None

        # Get the view class
        if hasattr(view_func, "view_class"):
            view_class = view_func.view_class
        elif hasattr(view_func, "cls"):
            view_class = view_func.cls
        elif inspect.isclass(view_func):
            view_class = view_func
        else:
            return None

        # Check if it's a HorillaListView and has columns defined
        if issubclass(view_class, HorillaListView):
            try:
                model = apps.get_model(app_label=app_label, model_name=model_name)

                # Get columns from the view class
                # Columns might be defined as class attribute
                if hasattr(view_class, "columns") and view_class.columns:
                    columns = view_class.columns
                    # Extract field names from columns
                    default_field_names = []
                    for col in columns:
                        if isinstance(col, (list, tuple)) and len(col) >= 2:
                            default_field_names.append(col[1])
                        elif isinstance(col, str):
                            default_field_names.append(col)
                    return default_field_names
            except Exception as e:
                logger.debug("Error getting columns from view: %s", str(e))
                return None
    except Exception as e:
        logger.debug("Error resolving URL name %s: %s", url_name, str(e))
        return None

    return None


@method_decorator(htmx_required, name="dispatch")
class HorillaKanbanGroupByView(FormView):
    """View for configuring kanban board group-by field settings."""

    template_name = "kanban_settings_form.html"
    form_class = KanbanGroupByForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        model_name = self.request.GET.get("model")
        app_label = self.request.GET.get("app_label")

        exclude_fields = self.request.POST.get(
            "exclude_fields"
        ) or self.request.GET.get("exclude_fields", None)

        if exclude_fields:
            exclude_fields = [f.strip() for f in exclude_fields.split(",") if f.strip()]
            exclude_fields = exclude_fields if exclude_fields else None
        else:
            exclude_fields = None

        include_fields = self.request.POST.get(
            "include_fields"
        ) or self.request.GET.get("include_fields", None)
        if include_fields:
            include_fields = [f.strip() for f in include_fields.split(",") if f.strip()]
            include_fields = include_fields if include_fields else None
        else:
            include_fields = None

        view_type = self.request.GET.get("view_type") or self.request.POST.get(
            "view_type"
        )
        if model_name and app_label:
            kwargs["instance"] = KanbanGroupBy(
                model_name=model_name,
                app_label=app_label,
                user=self.request.user,
                view_type=view_type,
            )
        kwargs["exclude_fields"] = exclude_fields
        kwargs["include_fields"] = include_fields
        kwargs["initial"] = kwargs.get("initial") or {}
        kwargs["initial"]["view_type"] = view_type
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        view_type = self.request.GET.get("view_type") or self.request.POST.get(
            "view_type"
        )
        context["group_by_view_type"] = view_type
        context["settings_title"] = (
            _("Group By Settings") if view_type == "group_by" else _("Kanban Settings")
        )
        return context

    def form_valid(self, form):
        form.instance.user = self.request.user  # set the user server-side
        form.instance.view_type = form.cleaned_data.get("view_type")
        form.save()
        view_type = form.instance.view_type
        if view_type == "group_by":
            script = "<script>closeModal();$('#groupByBtn').click();</script>"
        else:
            script = "<script>closeModal();$('#kanbanBtn').click();</script>"
        return HttpResponse(script)


@method_decorator(htmx_required, name="dispatch")
class ListColumnSelectFormView(LoginRequiredMixin, FormView):
    """View for selecting and adding columns to list views."""

    template_name = "add_column_to_list.html"
    form_class = ColumnSelectionForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        app_label = self.request.POST.get(
            "app_label", self.request.GET.get("app_label")
        )
        model_name = self.request.POST.get(
            "model_name", self.request.GET.get("model_name")
        )
        url_name = self.request.POST.get("url_name", self.request.GET.get("url_name"))
        model_name = model_name.strip('"') if model_name else model_name
        if model_name and "." in model_name:
            model_name = model_name.split(".")[-1]

        path_context = (
            urlparse(self.request.META.get("HTTP_REFERER", ""))
            .path.strip("/")
            .replace("/", "_")
        )
        path_context = re.sub(r"_\d+$", "", path_context)
        user = self.request.user

        if app_label and model_name and url_name:
            try:
                model = apps.get_model(app_label=app_label, model_name=model_name)
                kwargs["model"] = model
                kwargs["app_label"] = app_label
                kwargs["path_context"] = path_context
                kwargs["user"] = user
                kwargs["model_name"] = model_name
                kwargs["url_name"] = url_name
            except LookupError:
                self.form_error = "Invalid model specified."
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        app_label = self.request.GET.get(
            "app_label", self.request.POST.get("app_label")
        )
        model_name = self.request.GET.get(
            "model_name", self.request.POST.get("model_name")
        )
        url_name = self.request.GET.get("url_name", self.request.POST.get("url_name"))

        model_name = model_name.strip('"') if model_name else model_name
        if model_name and "." in model_name:
            model_name = model_name.split(".")[-1]
        path_context = (
            urlparse(self.request.META.get("HTTP_REFERER", ""))
            .path.strip("/")
            .replace("/", "_")
        )
        path_context = re.sub(r"_\d+$", "", path_context)
        context["app_label"] = app_label
        context["model_name"] = model_name
        context["url_name"] = url_name

        visible_fields = []
        all_fields = []
        removed_custom_field_lists = []
        visibility = None
        model = None

        if app_label and model_name:
            try:
                model = apps.get_model(app_label=app_label, model_name=model_name)
                instance = model()
                model_fields = [
                    [
                        force_str(f.verbose_name or f.name.title()),
                        (
                            f.name
                            if not getattr(f, "choices", None)
                            else f"get_{f.name}_display"
                        ),
                    ]
                    for f in model._meta.get_fields()
                    if isinstance(f, Field) and f.name not in ["history"]
                ]
                all_fields = (
                    getattr(instance, "columns", model_fields)
                    if hasattr(instance, "columns")
                    else model_fields
                )

                # Filter out hidden fields based on field permissions
                if all_fields:
                    field_names = [
                        f[1]
                        for f in all_fields
                        if isinstance(f, (list, tuple)) and len(f) >= 2
                    ]

                    # filter_hidden_fields now handles display methods internally
                    visible_field_names_from_perms = filter_hidden_fields(
                        self.request.user, model, field_names
                    )

                    # Filter all_fields - only keep fields that are visible
                    filtered_all_fields = []
                    for f in all_fields:
                        field_name = (
                            f[1]
                            if isinstance(f, (list, tuple)) and len(f) >= 2
                            else None
                        )
                        if field_name and field_name in visible_field_names_from_perms:
                            filtered_all_fields.append(f)

                    all_fields = filtered_all_fields

                session_key = (
                    f"visible_fields_{app_label}_{model_name}_{path_context}_{url_name}"
                )
                visibility = ListColumnVisibility.all_objects.filter(
                    user=self.request.user,
                    app_label=app_label,
                    model_name=model_name,
                    context=path_context,
                    url_name=url_name,
                ).first()
                if visibility:
                    visible_fields = visibility.visible_fields
                    # Filter out hidden fields from visible_fields as well
                    if visible_fields:
                        visible_field_names_list = [
                            f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                            for f in visible_fields
                        ]
                        visible_field_names_from_perms = filter_hidden_fields(
                            self.request.user, model, visible_field_names_list
                        )
                        visible_fields = [
                            f
                            for f in visible_fields
                            if (
                                f[1]
                                if isinstance(f, (list, tuple)) and len(f) >= 2
                                else f
                            )
                            in visible_field_names_from_perms
                        ]

                    # Get removed_custom_field_lists and filter hidden fields
                    removed_custom_field_lists = visibility.removed_custom_fields or []
                    # Filter out hidden fields from removed_custom_field_lists
                    if removed_custom_field_lists:
                        removed_field_names = [
                            f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                            for f in removed_custom_field_lists
                        ]
                        visible_removed_field_names = filter_hidden_fields(
                            self.request.user, model, removed_field_names
                        )
                        removed_custom_field_lists = [
                            f
                            for f in removed_custom_field_lists
                            if (
                                f[1]
                                if isinstance(f, (list, tuple)) and len(f) >= 2
                                else f
                            )
                            in visible_removed_field_names
                        ]

                self.request.session[session_key] = [
                    f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                    for f in visible_fields
                ]
                self.request.session.modified = True
            except LookupError:
                context["error"] = "Invalid model specified."

        context["visible_fields"] = visible_fields

        visible_field_names = [
            f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
            for f in visible_fields
        ]

        related_field_parents = set()
        for _, field_name in visible_fields + removed_custom_field_lists:
            if isinstance(field_name, (list, tuple)) and len(field_name) >= 2:
                field_name = field_name[1]
            if "__" in str(field_name):
                parent_field = str(field_name).split("__")[0]
                related_field_parents.add(parent_field)
        exclude_fields = self.request.GET.get("exclude")
        exclude_fields_list = exclude_fields.split(",") if exclude_fields else []
        context["exclude_fields"] = exclude_fields
        sensitive_fields = ["id", "additional_info"]

        # Build available_fields - all_fields and removed_custom_field_lists are already filtered for hidden fields
        # But do one final check to ensure no hidden fields slip through
        combined_fields = all_fields + removed_custom_field_lists

        if model and combined_fields:
            # Final safety check: filter hidden fields one more time
            combined_field_names = [
                f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                for f in combined_fields
            ]

            # filter_hidden_fields now handles display methods internally
            visible_combined_field_names = filter_hidden_fields(
                self.request.user, model, combined_field_names
            )

            # Only include fields that passed the permission check
            filtered_combined_fields = []
            for f in combined_fields:
                field_name = f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                if field_name in visible_combined_field_names:
                    filtered_combined_fields.append(f)

            combined_fields = filtered_combined_fields

        context["available_fields"] = [
            [verbose_name, field_name]
            for verbose_name, field_name in combined_fields
            if field_name not in visible_field_names
            and field_name not in related_field_parents
            and field_name not in exclude_fields_list
            and field_name not in sensitive_fields
        ]

        has_custom_visibility = False
        if app_label and model_name and model and url_name:
            view_default_field_names = get_default_columns_from_view(
                url_name, app_label, model_name, self.request
            )

            if view_default_field_names is None:
                view_default_field_names = []
                for f in all_fields:
                    if isinstance(f, (list, tuple)) and len(f) >= 2:
                        view_default_field_names.append(f[1])

            session_key = (
                f"visible_fields_{app_label}_{model_name}_{path_context}_{url_name}"
            )
            session_field_names = self.request.session.get(session_key, [])

            if session_field_names:
                current_field_names = session_field_names
            else:
                current_field_names = []
                for f in visible_fields:
                    if isinstance(f, (list, tuple)) and len(f) >= 2:
                        current_field_names.append(f[1])
                    elif isinstance(f, str):
                        current_field_names.append(f)

            has_removed_fields = bool(removed_custom_field_lists)

            default_set = set(view_default_field_names)
            current_set = set(current_field_names)

            has_added_fields = bool(current_set - default_set)
            has_removed_default_fields = bool(default_set - current_set)
            # Same fields but different order counts as custom (so "Reset to Default" shows)
            default_list = (
                list(view_default_field_names) if view_default_field_names else []
            )
            has_order_changed = (
                default_set == current_set
                and len(current_field_names) == len(default_list)
                and current_field_names != default_list
            )

            has_custom_visibility = (
                has_removed_fields
                or has_added_fields
                or has_removed_default_fields
                or has_order_changed
            )

        context["has_custom_visibility"] = has_custom_visibility

        if hasattr(self, "form_error"):
            context["error"] = self.form_error
        return context

    def form_valid(self, form):
        with translation.override("en"):
            app_label = self.request.POST.get("app_label")
            model_name = self.request.POST.get("model_name")
            url_name = self.request.POST.get("url_name")
            if model_name and "." in model_name:
                model_name = model_name.split(".")[-1]
            field_names = self.request.POST.getlist("visible_fields")

            if not app_label or not model_name:
                return JsonResponse(
                    {
                        "status": "error",
                        "message": "Missing app_label or model_name",
                        "htmx": '<div id="error-message">Missing app_label or model_name</div>',
                    }
                )

            path_context = (
                urlparse(self.request.META.get("HTTP_REFERER", ""))
                .path.strip("/")
                .replace("/", "_")
            )
            path_context = re.sub(r"_\d+$", "", path_context)
            try:
                model = apps.get_model(app_label=app_label, model_name=model_name)

                # Filter out hidden fields from field_names before processing
                if field_names:
                    field_names = filter_hidden_fields(
                        self.request.user, model, field_names
                    )
                instance = model()
                model_fields = [
                    [
                        force_str(f.verbose_name or f.name.title()),
                        (
                            f.name
                            if not getattr(f, "choices", None)
                            else f"get_{f.name}_display"
                        ),
                    ]
                    for f in model._meta.get_fields()
                    if isinstance(f, Field) and f.name not in ["history"]
                ]
                all_fields = (
                    getattr(instance, "columns", model_fields)
                    if hasattr(instance, "columns")
                    else model_fields
                )

                # Filter out hidden fields based on field permissions
                if all_fields:
                    field_names_list = [
                        f[1]
                        for f in all_fields
                        if isinstance(f, (list, tuple)) and len(f) >= 2
                    ]
                    visible_field_names_from_perms = filter_hidden_fields(
                        self.request.user, model, field_names_list
                    )
                    all_fields = [
                        f
                        for f in all_fields
                        if (
                            f[1]
                            if isinstance(f, (list, tuple)) and len(f) >= 2
                            else None
                        )
                        in visible_field_names_from_perms
                    ]

                all_field_names = {item[1] for item in all_fields}
                visibility = ListColumnVisibility.all_objects.filter(
                    user=self.request.user,
                    app_label=app_label,
                    model_name=model_name,
                    context=path_context,
                    url_name=url_name,
                ).first()
                custom_fields = []
                if visibility:
                    visible_fields_from_db = visibility.visible_fields
                    # Filter visible_fields from DB to exclude hidden fields
                    if visible_fields_from_db:
                        visible_field_names_list = [
                            f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                            for f in visible_fields_from_db
                        ]
                        visible_field_names_from_perms = filter_hidden_fields(
                            self.request.user, model, visible_field_names_list
                        )
                        visible_fields_from_db = [
                            f
                            for f in visible_fields_from_db
                            if (
                                f[1]
                                if isinstance(f, (list, tuple)) and len(f) >= 2
                                else f
                            )
                            in visible_field_names_from_perms
                        ]

                    for display_name, field_name in visible_fields_from_db:
                        if field_name not in all_field_names and field_name not in [
                            f[1]
                            for f in model_fields
                            if isinstance(f, (list, tuple)) and len(f) >= 2
                        ]:
                            custom_fields.append([display_name, field_name])
                all_fields = all_fields + custom_fields
                verbose_name_map = {f[1]: f[0] for f in all_fields}

                # Include removed custom fields in the verbose name map to preserve original display names
                removed_custom_field_lists = (
                    visibility.removed_custom_fields if visibility else []
                )
                # Filter out hidden fields from removed_custom_field_lists
                if removed_custom_field_lists:
                    removed_field_names = [
                        f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                        for f in removed_custom_field_lists
                    ]
                    visible_removed_field_names = filter_hidden_fields(
                        self.request.user, model, removed_field_names
                    )
                    removed_custom_field_lists = [
                        f
                        for f in removed_custom_field_lists
                        if (f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f)
                        in visible_removed_field_names
                    ]

                for display_name, field_name in removed_custom_field_lists:
                    verbose_name_map[field_name] = display_name

                model_field_names = {
                    f.name for f in model._meta.get_fields() if isinstance(f, Field)
                }

                visible_fields = [
                    [force_str(verbose_name_map.get(f, f.replace("_", " ").title())), f]
                    for f in field_names
                ]

                previous_visible_fields = (
                    visibility.visible_fields if visibility else []
                )
                previous_non_model_fields = [
                    f[1]
                    for f in previous_visible_fields
                    if f[1] not in model_field_names and not f[1].startswith("get_")
                ]
                removed_non_model_fields = [
                    [force_str(verbose_name_map.get(f, f.replace("_", " ").title())), f]
                    for f in previous_non_model_fields
                    if f not in field_names
                ]

                existing_removed = (
                    visibility.removed_custom_fields if visibility else []
                )
                # Only add to removed_custom_fields if not already there
                for removed_field in removed_non_model_fields:
                    if not any(
                        existing[1] == removed_field[1] for existing in existing_removed
                    ):
                        existing_removed.append(removed_field)

                # Remove fields from removed_custom_fields if they're being added back
                updated_removed_custom_fields = [
                    field for field in existing_removed if field[1] not in field_names
                ]

                session_key = (
                    f"visible_fields_{app_label}_{model_name}_{path_context}_{url_name}"
                )
                self.request.session[session_key] = field_names
                self.request.session.modified = True

                ListColumnVisibility.all_objects.filter(
                    user=self.request.user,
                    app_label=app_label,
                    model_name=model_name,
                    context=path_context,
                    url_name=url_name,
                ).delete()
                ListColumnVisibility.all_objects.create(
                    user=self.request.user,
                    app_label=app_label,
                    model_name=model_name,
                    visible_fields=visible_fields,
                    removed_custom_fields=updated_removed_custom_fields,
                    context=path_context,
                    url_name=url_name,
                )

                cache_key = f"visible_columns_{self.request.user.id}_{app_label}_{model_name}_{path_context}_{url_name}"
                cache.delete(cache_key)

                return HttpResponse(
                    "<script>$('#reloadButton').click();closeModal();</script>"
                )
            except LookupError:
                return JsonResponse(
                    {
                        "status": "error",
                        "message": "Invalid model",
                        "htmx": '<div id="error-message">Invalid model</div>',
                    }
                )

    def form_invalid(self, form):
        context = self.get_context_data(form=form)
        context["error"] = "Form submission failed. Please review the selected fields."
        return self.render_to_response(context)


@method_decorator(htmx_required, name="dispatch")
class ResetColumnToDefaultView(LoginRequiredMixin, View):
    """View for resetting column visibility to default settings."""

    def post(self, request, *args, **kwargs):
        """
        Reset column visibility to default by deleting ListColumnVisibility record.

        Expects query parameters: app_label, model_name, url_name
        """
        app_label = request.POST.get("app_label") or request.GET.get("app_label")
        model_name = request.POST.get("model_name") or request.GET.get("model_name")
        url_name = request.POST.get("url_name") or request.GET.get("url_name")

        if not app_label or not model_name:
            return HttpResponse(
                "<div id='error-message'>Missing app_label or model_name</div>",
                status=400,
            )

        # Clean model_name if it contains app_label
        model_name = model_name.strip('"') if model_name else model_name
        if model_name and "." in model_name:
            model_name = model_name.split(".")[-1]

        path_context = (
            urlparse(request.META.get("HTTP_REFERER", ""))
            .path.strip("/")
            .replace("/", "_")
        )
        path_context = re.sub(r"_\d+$", "", path_context)

        try:
            ListColumnVisibility.all_objects.filter(
                user=request.user,
                app_label=app_label,
                model_name=model_name,
                context=path_context,
                url_name=url_name,
            ).delete()

            session_key = (
                f"visible_fields_{app_label}_{model_name}_{path_context}_{url_name}"
            )
            if session_key in request.session:
                del request.session[session_key]
                request.session.modified = True

            cache_key = (
                f"visible_columns_{request.user.id}_{app_label}_{model_name}_"
                f"{path_context}_{url_name}"
            )
            cache.delete(cache_key)

            # Return response that reloads the page
            return HttpResponse(
                "<script>$('#reloadButton').click();closeModal();</script>"
            )
        except Exception as e:
            logger.error("Error resetting columns to default: %s", str(e))
            return HttpResponse(
                f"<div id='error-message'>Error resetting columns: {str(e)}</div>",
                status=500,
            )


@method_decorator(htmx_required, name="dispatch")
class DetailFieldSelectorView(LoginRequiredMixin, View):
    """View for selecting header and details fields in detail views."""

    template_name = "add_field_to_detail.html"

    def get(self, request, *args, **kwargs):
        app_label = request.GET.get("app_label")
        model_name = request.GET.get("model_name")
        url_name = request.GET.get("url_name")
        model_name = model_name.strip('"') if model_name else model_name
        if model_name and "." in model_name:
            model_name = model_name.split(".")[-1]
        if not app_label or not model_name or not url_name:
            return HttpResponse(
                "<div id='error-message'>Missing app_label, model_name or url_name</div>",
                status=400,
            )
        try:
            model = apps.get_model(app_label=app_label, model_name=model_name)
        except LookupError:
            return HttpResponse(
                "<div id='error-message'>Invalid model</div>", status=400
            )

        instance = model()
        base_excluded = {
            "id",
            "created_at",
            "updated_at",
            "history",
            "is_active",
            "additional_info",
            "created_by",
            "updated_by",
        }
        header_excluded = set(base_excluded)
        details_excluded = set(base_excluded)

        detail_view_class = HorillaDetailView._view_registry.get(model)
        if detail_view_class:
            header_excluded.update(getattr(detail_view_class, "excluded_fields", []))
            pf = getattr(detail_view_class, "pipeline_field", None)
            if pf:
                pf_str = str(pf)
                header_excluded.add(pf_str)
                details_excluded.add(pf_str)
            details_url = getattr(detail_view_class, "details_section_url_name", None)
            if not details_url:
                details_url = request.GET.get("details_section_url") or None
            details_excluded_override = getattr(
                detail_view_class, "details_excluded_fields", None
            )
            if details_url:
                try:
                    from django.urls import resolve, reverse

                    resolved = resolve(reverse(details_url, kwargs={"pk": 1}))
                    section_view = getattr(resolved.func, "view_class", None)
                    if section_view:
                        view_inst = section_view()
                        view_inst.request = request
                        view_inst.model = model
                        details_excluded.update(
                            view_inst.get_excluded_fields()
                            if hasattr(view_inst, "get_excluded_fields")
                            else getattr(view_inst, "excluded_fields", [])
                        )
                except Exception:
                    details_excluded.update(header_excluded)
            elif details_excluded_override is not None:
                details_excluded.update(details_excluded_override)
            else:
                details_excluded.update(
                    getattr(detail_view_class, "excluded_fields", [])
                )

        all_model_fields = [
            [force_str(f.verbose_name or f.name.title()), f.name]
            for f in model._meta.get_fields()
            if isinstance(f, Field)
            and f.name not in ["history"]
            and f.name not in base_excluded
        ]
        field_names = [f[1] for f in all_model_fields]
        visible = filter_hidden_fields(request.user, model, field_names)
        all_model_fields = [f for f in all_model_fields if f[1] in visible]

        default_header, default_details = _get_detail_field_defaults(model, request)

        visibility = DetailFieldVisibility.all_objects.filter(
            user=request.user,
            app_label=app_label,
            model_name=model_name,
            url_name=url_name,
        ).first()
        header_fields = (
            visibility.header_fields
            if visibility and visibility.header_fields
            else default_header
        )
        details_fields = (
            visibility.details_fields
            if visibility and visibility.details_fields
            else default_details
        )

        def resolve_verbose_names(fields_list):
            """Resolve verbose_name from model for current request language."""
            result = []
            for f in fields_list:
                fn = f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else f
                try:
                    mf = model._meta.get_field(str(fn))
                    result.append([mf.verbose_name, str(fn)])
                except Exception:
                    result.append(
                        [f[0] if isinstance(f, (list, tuple)) else str(fn), str(fn)]
                    )
            return result

        header_fields = resolve_verbose_names(header_fields)
        details_fields = resolve_verbose_names(details_fields)
        # Never show excluded fields in Visible lists (e.g. section view excluded_fields)
        header_fields = [f for f in header_fields if f[1] not in header_excluded]
        details_fields = [f for f in details_fields if f[1] not in details_excluded]
        # Filter out hidden fields based on field permissions (don't show in Visible lists)
        header_field_names_list = [f[1] for f in header_fields]
        details_field_names_list = [f[1] for f in details_fields]
        visible_header_names = filter_hidden_fields(
            request.user, model, header_field_names_list
        )
        visible_details_names = filter_hidden_fields(
            request.user, model, details_field_names_list
        )
        header_fields = [f for f in header_fields if f[1] in visible_header_names]
        details_fields = [f for f in details_fields if f[1] in visible_details_names]
        header_field_names = {f[1] for f in header_fields}
        details_field_names = {f[1] for f in details_fields}
        header_available = []
        details_available = []
        for _, fn in all_model_fields:
            try:
                vn = model._meta.get_field(fn).verbose_name
                if fn not in header_field_names and fn not in header_excluded:
                    header_available.append([vn, fn])
                if fn not in details_field_names and fn not in details_excluded:
                    details_available.append([vn, fn])
            except Exception:
                pass

        # Only show "Reset to Default" when the saved config actually differs from default.
        # If the user saved without making changes, visibility exists but matches default.
        has_custom = False
        if visibility and (visibility.header_fields or visibility.details_fields):

            def _field_names(fields):
                return [
                    f[1] if isinstance(f, (list, tuple)) and len(f) >= 2 else str(f)
                    for f in (fields or [])
                ]

            saved_header_names = _field_names(visibility.header_fields)
            saved_details_names = _field_names(visibility.details_fields)
            default_header_names = _field_names(default_header)
            default_details_names = _field_names(default_details)
            has_custom = (
                saved_header_names != default_header_names
                or saved_details_names != default_details_names
            )

        return render(
            request,
            self.template_name,
            {
                "app_label": app_label,
                "model_name": model_name,
                "url_name": url_name,
                "header_fields": header_fields,
                "header_available": header_available,
                "details_fields": details_fields,
                "details_available": details_available,
                "has_custom_visibility": has_custom,
            },
        )


@method_decorator(htmx_required, name="dispatch")
class ResetDetailFieldsView(LoginRequiredMixin, View):
    """Reset detail view fields to default."""

    def post(self, request, *args, **kwargs):
        app_label = request.POST.get("app_label")
        model_name = request.POST.get("model_name")
        url_name = request.POST.get("url_name")
        if model_name and "." in model_name:
            model_name = model_name.split(".")[-1]
        if app_label and model_name and url_name:
            DetailFieldVisibility.all_objects.filter(
                user=request.user,
                app_label=app_label,
                model_name=model_name,
                url_name=url_name,
            ).delete()
        return HttpResponse(
            "<script>closeContentModal();$('#reloadButton').click();</script>"
        )


@method_decorator(htmx_required, name="dispatch")
class SaveDetailFieldsView(LoginRequiredMixin, View):
    """Save header and details field order in one request (no per-move requests)."""

    def post(self, request, *args, **kwargs):
        app_label = request.POST.get("app_label")
        model_name = request.POST.get("model_name")
        url_name = request.POST.get("url_name")
        header_field_names = request.POST.getlist("header_fields")
        details_field_names = request.POST.getlist("details_fields")
        if model_name and "." in model_name:
            model_name = model_name.split(".")[-1]
        if not app_label or not model_name or not url_name:
            return HttpResponse(status=400)
        try:
            model = apps.get_model(app_label=app_label, model_name=model_name)
        except LookupError:
            return HttpResponse(status=400)
        header_field_names = filter_hidden_fields(
            request.user, model, header_field_names
        )
        details_field_names = filter_hidden_fields(
            request.user, model, details_field_names
        )
        all_model_fields = {
            f.name: force_str(f.verbose_name or f.name.title())
            for f in model._meta.get_fields()
            if isinstance(f, Field) and f.name not in ["history"]
        }
        header_fields = [
            [all_model_fields.get(fn, fn.replace("_", " ").title()), fn]
            for fn in header_field_names
        ]
        details_fields = [
            [all_model_fields.get(fn, fn.replace("_", " ").title()), fn]
            for fn in details_field_names
        ]
        default_header, default_details = _get_detail_field_defaults(model, request)
        visibility, _ = DetailFieldVisibility.all_objects.get_or_create(
            user=request.user,
            app_label=app_label,
            model_name=model_name,
            url_name=url_name,
            defaults={
                "header_fields": default_header,
                "details_fields": default_details,
            },
        )
        visibility.header_fields = _ensure_json_serializable(header_fields)
        visibility.details_fields = _ensure_json_serializable(details_fields)
        visibility.save()
        return HttpResponse(
            "<script>closeContentModal();$('#reloadButton').click();</script>"
        )


@method_decorator(htmx_required, name="dispatch")
class SaveFilterListView(LoginRequiredMixin, FormView):
    """View for saving and editing filter configurations as reusable filter lists."""

    template_name = "save_filter_form.html"
    form_class = SaveFilterListForm

    def get_initial(self):
        initial = super().get_initial()
        saved_list_id = self.request.GET.get("saved_list_id") or self.request.POST.get(
            "saved_list_id"
        )
        is_get = self.request.method == "GET"
        if saved_list_id:
            try:
                saved_list = self.request.user.saved_filter_lists.get(id=saved_list_id)
                initial["saved_list_id"] = saved_list.id
                if is_get:
                    initial["list_name"] = saved_list.name
                    initial["model_name"] = saved_list.model_name
                    initial["main_url"] = self.request.GET.get("main_url", "")
                    initial["make_public"] = saved_list.is_public
            except (
                ValueError,
                self.request.user.saved_filter_lists.model.DoesNotExist,
            ):
                if saved_list_id:
                    try:
                        initial["saved_list_id"] = int(saved_list_id)
                    except (TypeError, ValueError):
                        pass
        if not initial.get("model_name"):
            initial["model_name"] = self.request.GET.get("model_name")
        if "main_url" not in initial or initial["main_url"] == "":
            initial["main_url"] = self.request.GET.get(
                "main_url", self.request.POST.get("main_url", "")
            )
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        saved_list_id = self.request.GET.get("saved_list_id") or self.request.POST.get(
            "saved_list_id"
        )
        if saved_list_id:
            try:
                saved_list = self.request.user.saved_filter_lists.get(id=saved_list_id)
                context["query_params"] = saved_list.filter_params or {}
                context["is_edit"] = True
            except (
                ValueError,
                self.request.user.saved_filter_lists.model.DoesNotExist,
            ):
                context["query_params"] = {}
                context["is_edit"] = False
        else:
            context["query_params"] = {
                k: v
                for k, v in self.request.GET.lists()
                if k
                in ["field", "operator", "value", "start_value", "end_value", "search"]
            }
            context["is_edit"] = False
        context["main_url"] = (
            self.request.GET.get("main_url")
            or self.request.POST.get("main_url")
            or context.get("main_url", "")
        )
        return context

    def form_valid(self, form):
        list_name = form.cleaned_data["list_name"]
        model_name = form.cleaned_data["model_name"]
        make_public = form.cleaned_data.get("make_public", False)
        saved_list_id = form.cleaned_data.get("saved_list_id")
        filter_params = {
            k: v
            for k, v in self.request.POST.lists()
            if k in ["field", "operator", "value", "start_value", "end_value"]
        }
        search_in_post = self.request.POST.getlist("search")
        if search_in_post:
            filter_params["search"] = search_in_post
        elif self.request.GET.get("search"):
            filter_params["search"] = [self.request.GET.get("search")]

        if saved_list_id:
            try:
                saved_filter_list = self.request.user.saved_filter_lists.get(
                    id=saved_list_id
                )
                saved_filter_list.name = list_name
                saved_filter_list.filter_params = filter_params
                saved_filter_list.is_public = make_public
                saved_filter_list.save()
                main_url = form.cleaned_data["main_url"]
                view_type = f"saved_list_{saved_filter_list.id}"
                query_params = {
                    k: v
                    for k, v in self.request.GET.items()
                    if k not in ["view_type", "search"]
                }
                query_params["view_type"] = view_type
                redirect_url = f"{main_url}?{urlencode(query_params)}"
                return HttpResponseRedirect(redirect_url)
            except (
                ValueError,
                self.request.user.saved_filter_lists.model.DoesNotExist,
            ):
                form.add_error(
                    None,
                    "Saved list not found or you don't have permission to edit it.",
                )
                return self.form_invalid(form)

        if not any(filter_params.values()):
            form.add_error(None, "At least one filter is required.")
            return self.form_invalid(form)
        try:
            saved_filter_list, _created = (
                self.request.user.saved_filter_lists.update_or_create(
                    name=list_name,
                    model_name=model_name,
                    defaults={
                        "filter_params": filter_params,
                        "is_public": make_public,
                    },
                )
            )
            main_url = form.cleaned_data["main_url"]
            view_type = f"saved_list_{saved_filter_list.id}"
            query_params = {
                k: v
                for k, v in self.request.GET.items()
                if k not in ["view_type", "search"]
            }
            query_params["view_type"] = view_type

            redirect_url = f"{main_url}?{urlencode(query_params)}"
            return HttpResponseRedirect(redirect_url)
        except IntegrityError:
            form.add_error(
                "list_name", "A list with this name already exists for this model."
            )
            return self.form_invalid(form)

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


@method_decorator(htmx_required, name="dispatch")
class PinView(LoginRequiredMixin, View):
    """View for pinning and unpinning filter lists for quick access."""

    def post(self, request):
        """
        Toggle a pinned view for the current user.

        If `unpin` is provided, removes the pinned view; otherwise creates or
        updates the pinned view and returns the updated navbar HTML.
        """
        view_type = request.POST.get("view_type")
        model_name = request.POST.get("model_name")
        unpin = request.POST.get("unpin") or request.GET.get("unpin")

        if not view_type or not model_name:
            return HttpResponse(status=400)

        try:
            if unpin:
                PinnedView.all_objects.filter(
                    user=request.user, model_name=model_name
                ).delete()
                context = {
                    "request": request,
                    "model_name": model_name,
                    "view_type": view_type,
                    "all_view_types": True,
                }
                html = render_to_string("navbar.html", context)
                return HttpResponse(html)

            # else:
            PinnedView.all_objects.update_or_create(
                user=request.user,
                model_name=model_name,
                defaults={"view_type": view_type},
            )
            context = {
                "request": request,
                "model_name": model_name,
                "view_type": view_type,
                "pinned_view": {"view_type": view_type},
                "all_view_types": True,
            }
            html = render_to_string("navbar.html", context)
            return HttpResponse(html)
        except Exception:
            return HttpResponse(status=500)


@method_decorator(htmx_required, name="dispatch")
class DeleteSavedListView(LoginRequiredMixin, View):
    """View for deleting saved filter lists."""

    def post(self, request, *args, **kwargs):
        """
        Delete a user's saved filter list and update pinned views.

        Validates the provided `saved_list_id`, deletes it if permitted, and
        returns a redirect to `main_url` with an HTMX push header.
        """
        saved_list_id = request.POST.get("saved_list_id")
        main_url = request.POST.get("main_url")
        model_name = request.POST.get("model_name")  # Fallback to a default URL

        if not saved_list_id:
            messages.error(request, "Invalid saved list ID.")
            response = HttpResponseRedirect(main_url)
            response["HX-Push-Url"] = "true"  # Add HTMX header
            return response

        try:
            saved_list = request.user.saved_filter_lists.get(id=saved_list_id)
            saved_list_name = saved_list.name
            pinned_view = PinnedView.all_objects.filter(
                user=self.request.user,
                model_name=saved_list.model_name,
                view_type=f"saved_list_{saved_list_id}",
            ).first()
            if pinned_view:
                pinned_view.delete()

            saved_list.delete()
            messages.success(
                request, f"Saved list '{saved_list_name}' deleted successfully."
            )
        except Exception:
            messages.error(
                request,
                "Saved list not found or you don't have permission to delete it.",
            )

        query_params = request.GET.copy()
        pinned_view = PinnedView.all_objects.filter(
            user=self.request.user, model_name=model_name
        ).first()
        view_type = pinned_view.view_type if pinned_view else "all"
        query_params["view_type"] = view_type
        redirect_url = f"{main_url}?{urlencode(query_params)}"
        response = HttpResponseRedirect(redirect_url)
        response["HX-Push-Url"] = "true"
        return response


@method_decorator(htmx_required, name="dispatch")
class EditFieldView(LoginRequiredMixin, View):
    """
    View to render an editable field input for a specific object field.
    """

    template_name = "partials/edit_field.html"
    model = None

    def get_field_info(self, field, obj, user=None):
        """Get field information including type, choices, and current value"""
        field_info = {
            "name": field.name,
            "verbose_name": field.verbose_name,
            "field_type": "text",  # default
            "value": getattr(obj, field.name, ""),
            "choices": [],
            "display_value": str(getattr(obj, field.name, "")),
            "use_select2": False,  # Default to False
        }

        if isinstance(field, models.ManyToManyField):
            field_info["field_type"] = "select"
            field_info["multiple"] = True
            field_info["use_select2"] = True

            related_model = field.related_model
            field_info["related_app_label"] = related_model._meta.app_label
            field_info["related_model_name"] = related_model._meta.model_name

            # Get current values
            current_values = getattr(obj, field.name).values_list("pk", flat=True)
            field_info["value"] = list(current_values) if current_values else []

            # Get initial choices for selected items only
            field_info["choices"] = []
            if current_values:
                selected_objects = related_model.objects.filter(pk__in=current_values)
                field_info["choices"] = [
                    {"value": obj.pk, "label": str(obj)} for obj in selected_objects
                ]

            field_info["display_value"] = (
                ", ".join(str(item) for item in getattr(obj, field.name).all())
                if getattr(obj, field.name).exists()
                else ""
            )

        elif isinstance(field, models.ForeignKey):
            field_info["field_type"] = "select"
            field_info["use_select2"] = True

            related_model = field.related_model
            field_info["related_app_label"] = related_model._meta.app_label
            field_info["related_model_name"] = related_model._meta.model_name

            # Get current value
            current_obj = getattr(obj, field.name)
            field_info["value"] = current_obj.pk if current_obj else ""

            # Get initial choices - only the selected item if exists
            field_info["choices"] = [{"value": "", "label": "---------"}]
            if current_obj:
                field_info["choices"].append(
                    {"value": current_obj.pk, "label": str(current_obj)}
                )

            field_info["display_value"] = str(current_obj) if current_obj else ""

        elif hasattr(field, "choices") and field.choices:
            field_info["field_type"] = "select"
            field_info["choices"] = [{"value": "", "label": "---------"}]
            field_info["choices"].extend(
                [{"value": choice[0], "label": choice[1]} for choice in field.choices]
            )
            field_info["display_value"] = getattr(obj, f"get_{field.name}_display")()

        elif isinstance(field, models.BooleanField):
            field_info["field_type"] = "select"
            field_info["choices"] = [
                {"value": "", "label": "---------"},
                {"value": "True", "label": "Yes"},
                {"value": "False", "label": "No"},
            ]
            current_value = getattr(obj, field.name)
            field_info["value"] = (
                str(current_value) if current_value is not None else ""
            )
            field_info["display_value"] = (
                "Yes" if current_value else "No" if current_value is False else ""
            )

        elif isinstance(field, models.EmailField):
            field_info["field_type"] = "email"

        elif isinstance(field, models.URLField):
            field_info["field_type"] = "url"

        elif isinstance(
            field,
            (models.IntegerField, models.BigIntegerField, models.SmallIntegerField),
        ):
            field_info["field_type"] = "number"

        elif isinstance(field, (models.DecimalField, models.FloatField)):
            field_info["field_type"] = "number"
            field_info["step"] = "0.01"

        elif isinstance(field, models.DateTimeField):
            field_info["field_type"] = "datetime-local"
            if field_info["value"]:
                dt_value = field_info["value"]

                # Convert to user's timezone if available
                if user and hasattr(user, "time_zone") and user.time_zone:
                    try:
                        user_tz = pytz.timezone(user.time_zone)
                        # Make aware if naive
                        if timezone.is_naive(dt_value):
                            dt_value = timezone.make_aware(
                                dt_value, timezone.get_default_timezone()
                            )
                        # Convert to user timezone
                        dt_value = dt_value.astimezone(user_tz)
                    except Exception:
                        pass

                # Format for datetime-local input (without timezone info)
                field_info["value"] = dt_value.strftime("%Y-%m-%dT%H:%M")

                # Display value with user's format
                if user and hasattr(user, "date_time_format") and user.date_time_format:
                    try:
                        field_info["display_value"] = dt_value.strftime(
                            user.date_time_format
                        )
                    except Exception:
                        field_info["display_value"] = dt_value.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                else:
                    field_info["display_value"] = dt_value.strftime("%Y-%m-%d %H:%M:%S")

        elif isinstance(field, models.DateField):
            field_info["field_type"] = "date"
            if field_info["value"]:
                date_value = field_info["value"]
                field_info["value"] = date_value.strftime("%Y-%m-%d")

                # Display value with user's format
                if user and hasattr(user, "date_format") and user.date_format:
                    try:
                        field_info["display_value"] = date_value.strftime(
                            user.date_format
                        )
                    except Exception:
                        field_info["display_value"] = date_value.strftime("%Y-%m-%d")
                else:
                    field_info["display_value"] = date_value.strftime("%Y-%m-%d")

        elif isinstance(field, models.TextField):
            field_info["field_type"] = "textarea"

        return field_info

    def get(self, request, pk, field_name, app_label, model_name):
        """
        Render the editable field input for the given object and field.

        Loads the object and field metadata and returns the rendered edit field
        template or a JS snippet to trigger a page reload on error.
        """
        pipeline_field = request.GET.get("pipeline_field", None)
        try:
            if not self.model:
                self.model = apps.get_model(app_label, model_name)
            obj = get_object_or_404(self.model, pk=pk)
            field = next(
                (f for f in obj._meta.get_fields() if f.name == field_name), None
            )
        except Exception as e:
            messages.error(self.request, e)
            return HttpResponse("<script>$('#reloadButton').click();</script>")

        field_info = self.get_field_info(field, obj, request.user)

        context = {
            "object_id": pk,
            "field_info": field_info,
            "app_label": app_label,
            "model_name": model_name,
            "pipeline_field": pipeline_field,
        }
        return render(request, self.template_name, context)


@method_decorator(htmx_required, name="dispatch")
class UpdateFieldView(LoginRequiredMixin, View):
    """
    View to handle updating a single field of an object.
    """

    template_name = "partials/field_display.html"
    model = None

    def post(self, request, pk, field_name, app_label, model_name):
        """
        Update a single field on an object based on submitted POST data.

        Handles many-to-many and simple field updates and returns an appropriate
        HTTP response or error status on failure.
        """
        try:
            if not self.model:
                self.model = apps.get_model(app_label, model_name)
            obj = get_object_or_404(self.model, pk=pk)
            field = next(
                (f for f in obj._meta.get_fields() if f.name == field_name), None
            )
        except Exception as e:
            messages.error(self.request, e)
            return HttpResponse("<script>$('#reloadButton').click();</script>")

        if not field:
            return HttpResponse(status=404)

        if isinstance(field, models.ManyToManyField):
            values = request.POST.getlist(f"{field_name}[]")  # Get list of selected IDs
            try:
                # Clear existing relationships and set new ones
                related_manager = getattr(obj, field_name)
                related_manager.clear()
                if values and values != [""]:  # Only add if there are selected values
                    related_manager.add(*values)
            except Exception as e:
                return HttpResponse(f"Error updating field: {str(e)}", status=400)
        else:

            value = request.POST.get(field_name)

            if value is not None:
                try:
                    # Handle different field types
                    if isinstance(field, models.ForeignKey):
                        if value == "":
                            setattr(obj, field_name, None)
                        else:
                            related_obj = field.related_model.objects.get(pk=value)
                            setattr(obj, field_name, related_obj)

                    elif isinstance(field, models.BooleanField):
                        if value == "":
                            setattr(obj, field_name, None)
                        else:
                            setattr(obj, field_name, value == "True")

                    elif isinstance(
                        field,
                        (
                            models.IntegerField,
                            models.BigIntegerField,
                            models.SmallIntegerField,
                        ),
                    ):
                        setattr(obj, field_name, int(value) if value else None)

                    elif isinstance(field, models.DecimalField):
                        if value:
                            try:
                                setattr(obj, field_name, Decimal(value))
                            except InvalidOperation:
                                return HttpResponse(
                                    f"Invalid decimal value: {escape(value)}",
                                    status=400,
                                )
                        else:
                            setattr(obj, field_name, None)

                    elif isinstance(field, models.FloatField):
                        setattr(obj, field_name, float(value) if value else None)

                    elif isinstance(field, models.DateTimeField):
                        if value:
                            try:
                                # Parse the datetime from the input (in user's timezone)
                                parsed_value = datetime.fromisoformat(value)

                                # Get user's timezone
                                user = request.user
                                if hasattr(user, "time_zone") and user.time_zone:
                                    try:
                                        user_tz = pytz.timezone(user.time_zone)
                                        # Make the parsed datetime aware in user's timezone
                                        parsed_value = user_tz.localize(parsed_value)
                                        # Convert to UTC or default timezone for storage
                                        parsed_value = parsed_value.astimezone(
                                            timezone.get_default_timezone()
                                        )
                                    except Exception:
                                        # Fallback: make aware with default timezone
                                        parsed_value = timezone.make_aware(
                                            parsed_value,
                                            timezone.get_default_timezone(),
                                        )
                                else:
                                    # No user timezone, use default
                                    parsed_value = timezone.make_aware(
                                        parsed_value, timezone.get_default_timezone()
                                    )

                                setattr(obj, field_name, parsed_value)
                            except ValueError as e:
                                return HttpResponse(
                                    f"Invalid datetime format: {escape(value)}",
                                    status=400,
                                )
                        else:
                            setattr(obj, field_name, None)

                    elif isinstance(field, models.DateField):
                        if value:
                            try:
                                parsed_value = datetime.fromisoformat(value).date()
                                setattr(obj, field_name, parsed_value)
                            except ValueError:
                                return HttpResponse(
                                    f"Invalid date format: {escape(value)}", status=400
                                )
                        else:
                            setattr(obj, field_name, None)

                    else:
                        setattr(obj, field_name, value)

                    obj.save()

                except Exception as e:
                    return HttpResponse(f"Error updating field: {str(e)}", status=400)

        # Get updated field info for display
        edit_view = EditFieldView()
        field_info = edit_view.get_field_info(field, obj, request.user)

        context = {
            "field_info": field_info,
            "object_id": pk,
            "app_label": app_label,
            "model_name": model_name,
        }
        return render(request, self.template_name, context)


@method_decorator(htmx_required, name="dispatch")
class CancelEditView(LoginRequiredMixin, View):
    """
    View to cancel editing and return to display mode without saving.
    """

    template_name = "partials/field_display.html"
    model = None

    def get(self, request, pk, field_name, app_label, model_name):
        """
        Return the display mode for a field after canceling edit.

        Re-uses EditFieldView.get_field_info to provide field rendering without
        making changes to the object.
        """
        try:
            if not self.model:
                self.model = apps.get_model(app_label, model_name)
            obj = get_object_or_404(self.model, pk=pk)
            field = next(
                (f for f in obj._meta.get_fields() if f.name == field_name), None
            )
        except Exception as e:
            messages.error(self.request, e)
            return HttpResponse("<script>$('#reloadButton').click();</script>")

        # Use the same field info structure as EditFieldView
        edit_view = EditFieldView()
        field_info = edit_view.get_field_info(field, obj)

        context = {
            "field_info": field_info,
            "object_id": pk,
            "app_label": app_label,
            "model_name": model_name,
        }
        return render(request, self.template_name, context)


@method_decorator(htmx_required, name="dispatch")
class KanbanLoadMoreView(LoginRequiredMixin, View):
    """
    Handle AJAX request to load more items for a specific Kanban column.
    """

    def get(self, request, app_label, model_name, *args, **kwargs):
        """
        Handle GET request to load more items for a specific Kanban column.
        """
        try:
            model = apps.get_model(
                app_label=app_label.split(".")[-1], model_name=model_name
            )
            view_class = HorillaKanbanView._view_registry.get(model)
            if not view_class:
                messages.error(request, f"View class {model_name} not found")
                return HttpResponse("<script>$('#reloadButton').click();")

            # FIX: Properly initialize the view with model
            view = view_class()
            view.request = request
            view.model = model
            view.kwargs = kwargs  # Pass kwargs if needed

            return view.load_more_items(request)
        except Exception as e:
            messages.error(request, f"Load More failed: {str(e)}")
            return HttpResponse("<script>$('#reloadButton').click();")


class GroupByLoadMoreView(LoginRequiredMixin, View):
    """
    Handle AJAX request to load more items for a specific group in the group-by view.
    """

    def get(self, request, app_label, model_name, *args, **kwargs):
        """
        Handle GET request to load more items for a specific group.
        """
        try:
            model = apps.get_model(
                app_label=app_label.split(".")[-1], model_name=model_name
            )
            view_class = HorillaGroupByView._view_registry.get(model)
            if not view_class:
                messages.error(request, f"View class {model_name} not found")
                return HttpResponse("<script>$('#reloadButton').click();")

            view = view_class()
            view.request = request
            view.model = model
            view.kwargs = kwargs

            return view.load_more_items(request)
        except Exception as e:
            messages.error(request, f"Load More failed: {str(e)}")
            return HttpResponse("<script>$('#reloadButton').click();")


class HorillaSelect2DataView(LoginRequiredMixin, View):
    """View for providing JSON data to Select2 AJAX dropdowns with search and pagination."""

    def get(self, request, *args, **kwargs):
        """
        Return JSON data for select2 AJAX queries.

        Expects `app_label` and `model_name` in `kwargs` and supports searching and
        paging parameters for select2 results.
        """
        if not request.headers.get("x-requested-with") == "XMLHttpRequest":
            return render(request, "error/405.html", status=405)
        app_label = kwargs.get("app_label")
        model_name = kwargs.get("model_name")
        field_name = request.GET.get("field_name")

        try:
            model = apps.get_model(app_label=app_label, model_name=model_name)
        except LookupError as e:
            raise HorillaHttp404(e)

        search_term = request.GET.get("q", "").strip()
        ids = request.GET.get("ids", "").strip()
        page = request.GET.get("page", "1")
        dependency_value = request.GET.get("dependency_value", "").strip()
        dependency_model = request.GET.get("dependency_model", "").strip()
        dependency_field = request.GET.get("dependency_field", "").strip()
        try:
            page = int(page)
        except ValueError:
            page = 1
        per_page = 10

        queryset = None

        # Try to get queryset from filter class first (NEW CODE)
        filter_class = self._get_filter_class_from_request(
            request, app_label, model_name
        )
        if filter_class and field_name:
            try:
                # Initialize filter with request to trigger OwnerFiltersetMixin
                filterset = filter_class(request=request, data={})
                if field_name in filterset.filters:
                    filter_obj = filterset.filters[field_name]
                    if hasattr(filter_obj, "field") and hasattr(
                        filter_obj.field, "queryset"
                    ):
                        queryset = filter_obj.field.queryset
                        logger.info(
                            "[Select2] Using queryset from filter class for %s",
                            field_name,
                        )
            except Exception as e:
                logger.error("[Select2] Could not resolve queryset from filter: %s", e)

        # Fallback to form class (EXISTING CODE)
        form_class = self._get_form_class_from_request(request)
        if form_class and field_name:
            try:
                form_kwargs = {"request": request}
                # Pass instance when object_id is provided (edit mode) so OwnerQuerysetMixin
                # uses change/change_own instead of add/add_own
                object_id = request.GET.get("object_id")
                if (
                    object_id
                    and hasattr(form_class, "_meta")
                    and hasattr(form_class._meta, "model")
                ):
                    parent_model = form_class._meta.model
                    try:
                        instance = parent_model.objects.get(pk=object_id)
                        form_kwargs["instance"] = instance
                    except (parent_model.DoesNotExist, ValueError):
                        pass
                form = form_class(**form_kwargs)
                if field_name in form.fields:
                    queryset = form.fields[field_name].queryset
            except Exception as e:
                logger.error("[Select2] Could not resolve queryset from form: %s", e)

        if queryset is None:
            queryset = model.objects.all()

        # Apply company filtering if model has company field and active_company is set
        company = getattr(request, "active_company", None)
        if company:
            # Check if the model has a company field
            try:
                model._meta.get_field("company")
                # Filter queryset by company
                queryset = queryset.filter(company=company)
            except Exception:
                # Model doesn't have a company field, skip filtering
                pass

        if dependency_value and dependency_model and dependency_field:
            try:
                dep_app_label, dep_model_name = dependency_model.split(".")
                related_model = apps.get_model(
                    app_label=dep_app_label, model_name=dep_model_name
                )

                field = model._meta.get_field(dependency_field)
                if field.related_model != related_model:
                    raise ValueError(
                        f"Field {dependency_field} does not reference {dependency_model}"
                    )

                filter_kwargs = {f"{dependency_field}__pk": dependency_value}
                queryset = queryset.filter(**filter_kwargs)
            except (ValueError, LookupError, AttributeError):
                queryset = queryset.none()

        if ids:
            try:
                id_list = [
                    int(id.strip()) for id in ids.split(",") if id.strip().isdigit()
                ]
                if id_list:
                    queryset = queryset.filter(pk__in=id_list)
                    results = [
                        {
                            "id": obj.pk,
                            "text": str(obj) or f"Unnamed {model_name} {obj.pk}",
                        }
                        for obj in queryset
                    ]
                    return JsonResponse(
                        {"results": results, "pagination": {"more": False}}
                    )
                # else:
                return JsonResponse({"results": [], "pagination": {"more": False}})
            except Exception:
                return JsonResponse({"results": [], "pagination": {"more": False}})

        if search_term:
            search_fields = [
                f.name
                for f in model._meta.fields
                if isinstance(f, (CharField, TextField)) and f.name != "id"
            ]
            if search_fields:
                query = Q()
                for field in search_fields:
                    query |= Q(**{f"{field}__icontains": search_term})
                queryset = queryset.filter(query)
            else:
                queryset = queryset.none()
        else:
            queryset = queryset.order_by("pk")

        paginator = Paginator(queryset, per_page)
        page_obj = paginator.get_page(page)

        results = [
            {"id": obj.pk, "text": str(obj) or f"Unnamed {model_name} {obj.pk}"}
            for obj in page_obj.object_list
        ]

        return JsonResponse(
            {"results": results, "pagination": {"more": page_obj.has_next()}}
        )

    def _get_filter_class_from_request(self, request, app_label, model_name):
        """
        Get the filter class for the model.

        Discovery order:
        1. Explicit filter_class parameter from request
        2. Search all FilterSet classes in filters module and match by Meta.model
        """
        filter_path = request.GET.get("filter_class")
        if filter_path:
            try:
                module_path, class_name = filter_path.rsplit(".", 1)
                module = importlib.import_module(module_path)
                return getattr(module, class_name)
            except Exception as e:
                logger.error(
                    "[Select2] Could not import filter_class %s: %s", filter_path, e
                )

        # Search all FilterSet classes in the module and match by Meta.model
        try:
            filters_module = importlib.import_module(f"{app_label}.filters")
            import django_filters

            model = apps.get_model(app_label=app_label, model_name=model_name)

            for name, obj in inspect.getmembers(filters_module, inspect.isclass):
                # Check if it's a FilterSet subclass (but not FilterSet itself)
                if (
                    issubclass(obj, django_filters.FilterSet)
                    and obj is not django_filters.FilterSet
                ):
                    # Check if Meta.model matches the requested model
                    if hasattr(obj, "Meta") and hasattr(obj.Meta, "model"):
                        if obj.Meta.model == model:
                            logger.info(
                                "[Select2] Found filter class by model match: %s", name
                            )
                            return obj
        except Exception as e:
            logger.debug("[Select2] Could not auto-discover filter class: %s", e)

        return None

    def _get_form_class_from_request(self, request):
        """
        Resolve which form is being used from form_class query param.
        DynamicForm is created inside get_form_class() and is not importable;
        when form_path contains DynamicForm, resolve via get_dynamic_form_for_model
        using parent_model  - works for any model, no per-model code.
        """
        form_path = request.GET.get("form_class")
        if not form_path:
            return None
        if "DynamicForm" in form_path:
            parent_model_path = request.GET.get("parent_model", "").strip()
            if parent_model_path and "." in parent_model_path:
                try:

                    p_app, p_model = parent_model_path.rsplit(".", 1)
                    parent_model = apps.get_model(app_label=p_app, model_name=p_model)
                    return get_dynamic_form_for_model(parent_model)
                except (LookupError, ValueError) as e:
                    logger.debug(
                        "[Select2] Could not resolve DynamicForm for parent_model %s: %s",
                        parent_model_path,
                        e,
                    )
            return None
        try:
            module_path, class_name = form_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            return getattr(module, class_name)
        except Exception as e:
            logger.error("[Select2] Could not import form_class %s: %s", form_path, e)
            return None


@method_decorator(htmx_required, name="dispatch")
class RemoveConditionRowView(LoginRequiredMixin, View):
    """View for removing condition rows from multi-condition filter forms."""

    def delete(self, request, row_id, *args, **kwargs):
        """
        Remove a condition row from a multi-condition form via HTMX.

        Returns an empty 200 response on success to indicate the row was removed.
        """

        return HttpResponse("")


@method_decorator(htmx_required, name="dispatch")
class GetFieldValueWidgetView(LoginRequiredMixin, View):
    """HTMX view to return dynamic value field widget based on selected field"""

    def get(self, request):
        """
        Return HTML for the input widget corresponding to the chosen field.

        Accepts query parameters to determine the row and field and returns the
        rendered widget HTML to be injected by HTMX.
        """
        row_id = request.GET.get("row_id", "")
        field_name = request.GET.get(f"field_{row_id}", request.GET.get("field", ""))
        model_name = request.GET.get("model_name", "")
        condition_model_str = request.GET.get("condition_model", "")

        # Try to get existing value from the request
        existing_value = request.GET.get(f"value_{row_id}", "")
        existing_operator = request.GET.get(f"operator_{row_id}", "")

        # Get the model field to determine appropriate widget
        widget_html = self._get_value_widget_html(
            field_name, model_name, row_id, existing_value
        )

        # For single-form condition fields: update operator dropdown by field type
        # (same operator matching as filter: boolean=equals/not_equals, text=contains/etc.)
        operator_oob = self._get_operator_oob_html(
            row_id, field_name, model_name, condition_model_str, existing_operator
        )
        if operator_oob:
            widget_html = widget_html + operator_oob

        return HttpResponse(widget_html)

    def _get_field_type_for_condition(self, model_field):
        """Return field type string for operator matching (same logic as filter)."""
        field_class_name = model_field.__class__.__name__
        if field_class_name == "ForeignKey":
            return "foreignkey"
        if hasattr(model_field, "choices") and model_field.choices:
            return "choice"
        if field_class_name == "DateTimeField":
            return "datetime"
        if field_class_name == "DateField":
            return "date"
        if field_class_name in ("BooleanField", "NullBooleanField"):
            return "boolean"
        return FIELD_TYPE_MAP.get(field_class_name, "other")

    def _get_operator_oob_html(
        self, row_id, field_name, model_name, condition_model_str, existing_operator
    ):
        """
        Return OOB (out-of-band) HTML to swap the operator dropdown in single-form
        condition fields. Operators are filtered by field type (same logic as filter).
        """
        if not condition_model_str or not row_id:
            return ""

        try:
            # Resolve target model and get selected field
            target_model = None
            for app_config in apps.get_app_configs():
                try:
                    target_model = apps.get_model(
                        app_label=app_config.label, model_name=model_name
                    )
                    break
                except LookupError:
                    continue
            if not target_model or not field_name:
                return ""

            try:
                model_field = target_model._meta.get_field(field_name)
            except Exception:
                return ""

            field_type = self._get_field_type_for_condition(model_field)
            allowed_operators = set(
                CONDITION_OPERATORS_BY_FIELD_TYPE.get(
                    field_type, CONDITION_OPERATORS_BY_FIELD_TYPE["other"]
                )
            )

            # Resolve condition model and get full operator choices
            condition_model = None
            parts = condition_model_str.split(".")
            model_name_part = parts[-1] if parts else ""
            app_label_part = (
                ".".join(parts[:-1]) if len(parts) > 1 else (parts[0] if parts else "")
            )
            try:
                condition_model = apps.get_model(app_label_part, model_name_part)
            except LookupError:
                pass
            if not condition_model:
                for app_config in apps.get_app_configs():
                    try:
                        candidate = apps.get_model(
                            app_label=app_config.label,
                            model_name=model_name_part,
                        )
                        if (
                            candidate
                            and f"{candidate._meta.app_label}.{candidate._meta.model_name}"
                            == condition_model_str
                        ):
                            condition_model = candidate
                            break
                    except LookupError:
                        continue
            if not condition_model:
                return ""
            try:
                op_field = condition_model._meta.get_field("operator")
                full_choices = list(getattr(op_field, "choices", []) or [])
            except Exception:
                return ""

            # Restrict to operators allowed for this field type (like filter)
            operator_choices = [("", "---------")] + [
                (v, label) for v, label in full_choices if v in allowed_operators
            ]

            options = []
            for val, label in operator_choices:
                selected = (
                    ' selected="selected"' if str(val) == str(existing_operator) else ""
                )
                options.append(
                    f'<option value="{force_str(val)}"{selected}>{force_str(label)}</option>'
                )
            options_html = "".join(options)
            safe_row_id = force_str(row_id).replace('"', "&quot;")
            return (
                f'<div id="id_operator_{safe_row_id}_container" hx-swap-oob="true">'
                f'<select name="operator_{safe_row_id}" id="id_operator_{safe_row_id}" '
                f'class="js-example-basic-single headselect" '
                f'data-placeholder="Select Operator">'
                f"{options_html}</select></div>"
            )
        except Exception as e:
            logger.debug("GetFieldValueWidgetView operator OOB: %s", e)
            return ""

    def _get_value_widget_html(self, field_name, model_name, row_id, existing_value=""):
        """Generate appropriate widget HTML based on selected field"""

        if not field_name or not model_name:
            # Return default text input
            return self._render_text_input(row_id, existing_value)

        try:
            # Find the model
            model = None
            for app_config in apps.get_app_configs():
                try:
                    model = apps.get_model(
                        app_label=app_config.label, model_name=model_name
                    )
                    break
                except LookupError:
                    continue

            if not model:
                return self._render_text_input(row_id, existing_value)

            # Get the field from the model
            try:
                model_field = model._meta.get_field(field_name)
            except Exception:
                return self._render_text_input(row_id, existing_value)

            # Determine widget type based on field type
            if isinstance(model_field, models.ForeignKey):
                related_model = model_field.related_model
                # Get all objects for the select, but ensure existing_value is included
                queryset = related_model.objects.all()
                choices = [(obj.pk, str(obj)) for obj in queryset]
                # If existing_value is provided but not in choices, try to find the object
                if existing_value and existing_value not in [
                    str(c[0]) for c in choices
                ]:
                    try:
                        existing_obj = related_model.objects.get(pk=existing_value)
                        # Add it to choices if not already there
                        if (existing_obj.pk, str(existing_obj)) not in choices:
                            choices.insert(
                                1, (existing_obj.pk, str(existing_obj))
                            )  # Insert after empty option
                    except (related_model.DoesNotExist, ValueError):
                        pass
                return self._render_select_input(choices, row_id, existing_value)
            if hasattr(model_field, "choices") and model_field.choices:
                return self._render_select_input(
                    model_field.choices, row_id, existing_value
                )
            if isinstance(model_field, models.BooleanField):
                return self._render_boolean_input(row_id, existing_value)
            if isinstance(model_field, models.DateField):
                return self._render_date_input(row_id, existing_value)
            if isinstance(model_field, models.DateTimeField):
                return self._render_datetime_input(row_id, existing_value)
            if isinstance(model_field, models.TimeField):
                return self._render_time_input(row_id, existing_value)
            if isinstance(model_field, models.IntegerField):
                return self._render_number_input(row_id, existing_value)
            if isinstance(model_field, models.DecimalField):
                return self._render_number_input(row_id, existing_value, step="0.01")
            if isinstance(model_field, models.EmailField):
                return self._render_email_input(row_id, existing_value)
            if isinstance(model_field, models.URLField):
                return self._render_url_input(row_id, existing_value)
            if isinstance(model_field, models.TextField):
                return self._render_textarea_input(row_id, existing_value)
            # else:
            return self._render_text_input(row_id, existing_value)

        except Exception as e:
            logger.error("Error generating value widget: %s", str(e))
            return self._render_text_input(row_id, existing_value)

    def _render_text_input(self, row_id, existing_value=""):
        return f"""
        <input type="text" name="value_{row_id}"  id="id_value_{row_id}" value="{existing_value}" placeholder="Enter Value"
            class="text-color-820 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md  focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600"
        >
        """

    def _render_select_input(self, choices, row_id, existing_value=""):
        options = '<option value="">---------</option>'
        for choice_value, choice_label in choices:
            selected = "selected" if str(choice_value) == str(existing_value) else ""
            options += (
                f'<option value="{choice_value}" {selected}>{choice_label}</option>'
            )

        return f"""<select name="value_{row_id}" id="id_value_{row_id}" class="js-example-basic-single headselect">{options}</select>"""

    def _render_boolean_input(self, row_id, existing_value=""):
        true_selected = "selected" if existing_value == "True" else ""
        false_selected = "selected" if existing_value == "False" else ""

        return f"""
        <select name="value_{row_id}"
                id="id_value_{row_id}"
                class="js-example-basic-single headselect">
            <option value="">---------</option>
            <option value="True" {true_selected}>True</option>
            <option value="False" {false_selected}>False</option>
        </select>
        """

    def _render_date_input(self, row_id, existing_value=""):
        return f"""
        <input type="date"
               name="value_{row_id}"
               id="id_value_{row_id}"
               value="{existing_value}"
               class="text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md  focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600">
        """

    def _render_datetime_input(self, row_id, existing_value=""):
        return f"""
        <input type="datetime-local"
               name="value_{row_id}"
               id="id_value_{row_id}"
               value="{existing_value}"
               class="text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md  focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600">
        """

    def _render_time_input(self, row_id, existing_value=""):
        return f"""
        <input type="time"
               name="value_{row_id}"
               id="id_value_{row_id}"
               value="{existing_value}"
               class="text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md  focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600">
        """

    def _render_number_input(self, row_id, existing_value="", step="1"):
        return f"""
        <input type="number"
               name="value_{row_id}"
               id="id_value_{row_id}"
               value="{existing_value}"
               step="{step}"
               class="text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md  focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600"
               placeholder="Enter Number">
        """

    def _render_email_input(self, row_id, existing_value=""):
        return f"""
        <input type="email"
               name="value_{row_id}"
               id="id_value_{row_id}"
               value="{existing_value}"
               class="text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md  focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600"
               placeholder="Enter Email">
        """

    def _render_url_input(self, row_id, existing_value=""):
        return f"""
        <input type="url"
               name="value_{row_id}"
               id="id_value_{row_id}"
               value="{existing_value}"
               class="text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md  focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600"
               placeholder="Enter URL">
        """

    def _render_textarea_input(self, row_id, existing_value=""):
        return f"""
        <textarea name="value_{row_id}"
                  id="id_value_{row_id}"
                  rows="3"
                  class="text-color-600 p-2 w-full border border-dark-50 rounded-md focus-visible:outline-0 text-sm transition focus:border-primary-600"
                  placeholder="Enter Value">{existing_value}</textarea>
        """


@method_decorator(htmx_required, name="dispatch")
class GetModelFieldChoicesView(LoginRequiredMixin, View):
    """
    Generic HTMX view to return field choices for a selected model/content_type.
    Returns all fields by default, but can be filtered via query parameters.
    """

    def get(self, request, *args, **kwargs):
        """Return a select element with field choices for the selected content type"""

        # Get parameters - support both 'content_type' and 'model' parameter names
        content_type_id = request.GET.get("content_type") or request.GET.get("model")
        row_id = request.GET.get("row_id", "0")

        # Get field name pattern - support different patterns
        field_name_pattern = request.GET.get("field_name_pattern", "field_{row_id}")
        field_name = field_name_pattern.format(row_id=row_id)
        field_id = f"id_{field_name}"

        if not content_type_id:
            return render(
                request,
                "partials/field_select_empty.html",
                {"field_name": field_name, "field_id": field_id},
            )

        try:
            content_type = HorillaContentType.objects.get(pk=content_type_id)
            model_name = content_type.model
        except HorillaContentType.DoesNotExist:
            return render(
                request,
                "partials/field_select_empty.html",
                {"field_name": field_name, "field_id": field_id},
            )

        # Get the model class
        model_class = None
        for app_config in apps.get_app_configs():
            try:
                model_class = apps.get_model(app_config.label, model_name.lower())
                break
            except (LookupError, ValueError):
                continue

        if not model_class:
            return render(
                request,
                "partials/field_select_empty.html",
                {"field_name": field_name, "field_id": field_id},
            )

        # Get filter parameters
        field_types = (
            request.GET.get("field_types", "").split(",")
            if request.GET.get("field_types")
            else []
        )
        exclude_fields = (
            request.GET.get("exclude_fields", "").split(",")
            if request.GET.get("exclude_fields")
            else []
        )
        exclude_choice_fields = (
            request.GET.get("exclude_choice_fields", "false").lower() == "true"
        )
        only_text_fields = (
            request.GET.get("only_text_fields", "false").lower() == "true"
        )

        # Default exclude fields
        default_exclude = [
            "id",
            "pk",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "company",
            "additional_info",
        ]
        exclude_fields = list(set(exclude_fields + default_exclude))

        # Build field choices
        # Use _meta.fields and _meta.many_to_many to get only forward fields (not reverse relations)
        # This excludes one-to-many and many-to-many reverse relationships
        field_choices = [("", "---------")]
        all_forward_fields = list(model_class._meta.fields) + list(
            model_class._meta.many_to_many
        )

        for field in all_forward_fields:
            if field.name in exclude_fields:
                continue
            # Skip non-editable fields (e.g. editable=False on the model)
            if not getattr(field, "editable", True):
                continue

            # Filter by field types if specified
            if field_types:
                field_type_name = field.__class__.__name__
                if field_type_name not in field_types:
                    continue

            # If only_text_fields is true, only include CharField, TextField, EmailField
            if only_text_fields:
                if not isinstance(
                    field, (models.CharField, models.TextField, models.EmailField)
                ):
                    continue

            # Skip fields with choices if specified
            if exclude_choice_fields:
                if hasattr(field, "choices") and field.choices:
                    continue

            verbose_name = (
                getattr(field, "verbose_name", None)
                or field.name.replace("_", " ").title()
            )
            field_choices.append((field.name, str(verbose_name).title()))

        # Build select HTML
        return render(
            request,
            "partials/field_select_empty.html",
            {
                "field_name": field_name,
                "field_id": field_id,
                "field_choices": field_choices,
            },
        )
