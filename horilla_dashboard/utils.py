"""Utility functions for horilla_dashboard app."""

import json
import logging
import traceback
import uuid
from datetime import datetime, timedelta

from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone

from horilla_utils.methods import get_section_info_for_model
from horilla_utils.middlewares import _thread_local

logger = logging.getLogger(__name__)

# Valid date range values (days)
DATE_RANGE_CHOICES = [7, 30, 60, 90]


def is_valid_date_range(value, date_from=None, date_to=None):
    """Return True if value is a valid date_range (including 'custom' when date_from or date_to given)."""
    if value in (None, "", "all"):
        return True
    if str(value) == "custom":
        return bool(date_from or date_to)
    return str(value) in [str(d) for d in DATE_RANGE_CHOICES]


def parse_date_param(value):
    """Parse YYYY-MM-DD string to date; return None if invalid or empty.
    Only accepts exactly 10-character YYYY-MM-DD (rejects trailing junk)."""
    if not value:
        return None
    s = str(value).strip()
    if len(s) != 10:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def get_date_field_for_model(model_class):
    """Get the first date field from model."""
    for field in model_class._meta.fields:
        if field.get_internal_type() in ["DateField", "DateTimeField"]:
            return field.name
    return None


def _custom_dates_invalid(date_from_raw, date_to_raw, parsed_from, parsed_to):
    """Return True if any supplied custom date param failed to parse (invalid format)."""
    had_from = date_from_raw is not None and str(date_from_raw).strip()
    had_to = date_to_raw is not None and str(date_to_raw).strip()
    return (had_from and parsed_from is None) or (had_to and parsed_to is None)


def validate_custom_date_params(date_range, date_from, date_to):
    """If date_range is 'custom' and any of date_from/date_to is invalid, return (None, None, None).
    Otherwise return (date_range, date_from, date_to). For valid custom range, date_from/date_to
    are returned as date objects so templates never display raw input."""
    if date_range != "custom" or (not date_from and not date_to):
        return (date_range, date_from, date_to)
    parsed_from = parse_date_param(date_from) if date_from else None
    parsed_to = parse_date_param(date_to) if date_to else None
    if _custom_dates_invalid(date_from, date_to, parsed_from, parsed_to):
        return (None, None, None)
    return (date_range, parsed_from, parsed_to)


def validate_date_range_request(request):
    """
    Validate date_range, date_from, date_to from request and return resolved values.
    Returns (date_range, date_from, date_to, redirect_url).
    If redirect_url is not None, the view should return redirect(redirect_url).
    Handles: invalid/malformed keys (date_range[]), duplicate keys, invalid dates, junk in dates, empty strings.
    """
    date_range = request.GET.get("date_range")
    date_from = request.GET.get("date_from") or None
    date_to = request.GET.get("date_to") or None
    if date_from == "":
        date_from = None
    if date_to == "":
        date_to = None

    date_range, date_from, date_to = validate_custom_date_params(
        date_range, date_from, date_to
    )
    if date_range is None and request.GET.get("date_range") == "custom":
        date_range = "all"
    if date_range is not None and not is_valid_date_range(
        date_range, date_from=date_from, date_to=date_to
    ):
        date_range = "all"
        date_from = date_to = None
    if date_range is None or date_range == "all":
        date_from = date_to = None

    query_params = request.GET.copy()
    for key in list(query_params.keys()):
        if (
            key in ("date_range", "date_from", "date_to")
            or key.startswith("date_range")
            or key.startswith("date_from")
            or key.startswith("date_to")
        ):
            query_params.pop(key, None)
    if date_range is None or date_range == "all":
        query_params["date_range"] = "all"
    elif date_range == "custom":
        query_params["date_range"] = "custom"
        if date_from is not None:
            query_params["date_from"] = (
                date_from.strftime("%Y-%m-%d")
                if hasattr(date_from, "strftime")
                else str(date_from)
            )
        if date_to is not None:
            query_params["date_to"] = (
                date_to.strftime("%Y-%m-%d")
                if hasattr(date_to, "strftime")
                else str(date_to)
            )
    else:
        query_params["date_range"] = str(date_range)

    date_keys = [
        k
        for k in request.GET.keys()
        if k in ("date_range", "date_from", "date_to")
        or k.startswith("date_range")
        or k.startswith("date_from")
        or k.startswith("date_to")
    ]
    malformed = any(k not in ("date_range", "date_from", "date_to") for k in date_keys)
    cur_dr = request.GET.get("date_range")
    cur_df = request.GET.get("date_from") or ""
    cur_dt = request.GET.get("date_to") or ""
    want_dr = query_params.get("date_range")
    want_df = query_params.get("date_from", "")
    want_dt = query_params.get("date_to", "")
    needs_redirect = (
        malformed or cur_dr != want_dr or cur_df != want_df or cur_dt != want_dt
    )
    if not date_keys and (date_range is None or date_range == "all"):
        needs_redirect = False
    redirect_url = None
    if needs_redirect:
        base_path = request.build_absolute_uri(request.path).split("?")[0]
        redirect_url = base_path + (
            "?" + query_params.urlencode() if query_params else ""
        )

    return redirect_url


def apply_date_range_to_queryset(
    queryset, model_class, date_range_days=None, date_from=None, date_to=None
):
    """Filter queryset by date range: either last N days or custom start/end (at least one required for custom).
    If custom range is requested but any date param is invalid, returns unfiltered queryset (all data).
    """
    date_field = get_date_field_for_model(model_class)
    if not date_field:
        return queryset

    if date_range_days == "custom" or date_from is not None or date_to is not None:
        date_from_raw = date_from
        date_to_raw = date_to
        if date_from is not None and not hasattr(date_from, "year"):
            date_from = parse_date_param(date_from)
        if date_to is not None and not hasattr(date_to, "year"):
            date_to = parse_date_param(date_to)
        if date_range_days == "custom" and _custom_dates_invalid(
            date_from_raw, date_to_raw, date_from, date_to
        ):
            return queryset
        if date_from is None and date_to is None:
            return queryset
        if date_from is not None:
            queryset = queryset.filter(**{f"{date_field}__date__gte": date_from})
        if date_to is not None:
            queryset = queryset.filter(**{f"{date_field}__date__lte": date_to})
        return queryset
    if not date_range_days:
        return queryset
    try:
        since = timezone.now() - timedelta(days=int(date_range_days))
        return queryset.filter(**{f"{date_field}__gte": since})
    except (TypeError, ValueError):
        return queryset


class DefaultDashboardGenerator:
    """
    Simple dashboard generator for specific predefined models
    """

    extra_models = []

    def __init__(
        self, user, company=None, date_range=None, date_from=None, date_to=None
    ):
        self.user = user
        self.company = company
        self.date_range = self._parse_date_range(date_range)
        parsed_from = parse_date_param(date_from) if date_from is not None else None
        parsed_to = parse_date_param(date_to) if date_to is not None else None
        if self.date_range == "custom" and _custom_dates_invalid(
            date_from, date_to, parsed_from, parsed_to
        ):
            self.date_range = None
            self.date_from = None
            self.date_to = None
        else:
            self.date_from = parsed_from
            self.date_to = parsed_to

        try:
            self.models = self.get_models()
        except ImportError:
            logger.warning("Horilla models not found, using empty model list")
            self.models = []

    @staticmethod
    def is_clear_range(date_range):
        """Return True if date_range means 'clear/no filter'."""
        return date_range in (None, "", "clear", "all")

    def _parse_date_range(self, date_range):
        """Parse and validate date_range (days or 'custom'). Returns None for clear, 30 if invalid."""
        if self.is_clear_range(date_range):
            return None
        if str(date_range) == "custom":
            return "custom"
        try:
            days = int(date_range)
            return days if days in DATE_RANGE_CHOICES else 30
        except (TypeError, ValueError):
            return 30

    def apply_date_range_filter(self, queryset, model_class):
        """Filter queryset to records within the selected date range."""
        if self.date_range == "custom":
            return apply_date_range_to_queryset(
                queryset,
                model_class,
                date_range_days="custom",
                date_from=self.date_from,
                date_to=self.date_to,
            )
        return apply_date_range_to_queryset(queryset, model_class, self.date_range)

    def get_models(self):
        """
        Child apps override this to return model list.
        """
        return self.extra_models

    def get_queryset(self, model_class):
        """Get filtered queryset for a model"""
        queryset = model_class.objects.all()

        app_label = model_class._meta.app_label
        model_name = model_class._meta.model_name

        has_view_all = self.user.has_perm(f"{app_label}.view_{model_name}")
        has_view_own = self.user.has_perm(f"{app_label}.view_own_{model_name}")

        if has_view_all:
            queryset = self.apply_date_range_filter(queryset, model_class)
            return queryset

        if has_view_own:

            if hasattr(model_class, "company") and self.company:
                queryset = queryset.filter(company=self.company)

            if hasattr(model_class, "OWNER_FIELDS"):
                owner_fields = model_class.OWNER_FIELDS
                if owner_fields and len(owner_fields) > 0:

                    q_objects = Q()
                    for field_name in owner_fields:
                        if hasattr(model_class, field_name):
                            q_objects |= Q(**{field_name: self.user})

                    if q_objects:
                        queryset = queryset.filter(q_objects)

            queryset = self.apply_date_range_filter(queryset, model_class)
            return queryset

        return queryset.none()

    def has_model_permission(self, model_class):
        """Check if user has either view or view_own permission for a model"""
        app_label = model_class._meta.app_label
        model_name = model_class._meta.model_name

        has_view_all = self.user.has_perm(f"{app_label}.view_{model_name}")
        has_view_own = self.user.has_perm(f"{app_label}.view_own_{model_name}")

        return has_view_all or has_view_own

    def generate_kpi_data(self):
        """Generate simple count KPIs only if include_kpi flag is True"""
        kpis = []

        for model_info in self.models:
            try:
                model_class = model_info["model"]

                # Only generate KPI if include_kpi flag is explicitly set to True
                include_kpi = model_info.get("include_kpi", False)

                if not include_kpi:
                    continue

                if self.has_model_permission(model_class):
                    count = self.get_queryset(model_info["model"]).count()

                    section_info = get_section_info_for_model(model_class)

                    kpi = {
                        "title": f"Total {model_info['name']}",
                        "value": count,
                        "icon": model_info["icon"],
                        "color": model_info["color"],
                        "url": section_info["url"],
                        "section": section_info["section"],
                        "type": "count",
                    }
                    kpis.append(kpi)

            except Exception as e:
                traceback.print_exc()
                logger.warning("Failed to generate KPI for %s:", e)

        return kpis

    def generate_chart_data(self):
        """Generate business-specific filtered charts"""
        charts = []

        for model_info in self.models[:5]:
            try:
                model_class = model_info["model"]

                if not self.has_model_permission(model_class):
                    continue

                queryset = self.get_queryset(model_class)
                count = queryset.count()

                chart_func = model_info.get("chart_func")

                if callable(chart_func):
                    if count == 0:
                        # Return empty chart with no_record message
                        chart = {
                            "title": model_info.get(
                                "name", model_class._meta.verbose_name_plural
                            ),
                            "type": "pie",  # Default type, won't be rendered anyway
                            "data": {
                                "labels": [],
                                "data": [],
                                "urls": [],
                                "labelField": "",
                            },
                            "is_empty": True,
                            "no_record_msg": f"No {model_info.get('name', model_class._meta.verbose_name_plural).lower()} found.",
                        }
                        charts.append(chart)
                    else:
                        chart = chart_func(self, queryset, model_info)

                        # Post-process chart data to handle choice fields
                        if chart and isinstance(chart, dict) and "data" in chart:
                            chart = self._convert_choice_labels_in_chart(
                                chart, model_class
                            )
                            chart["is_empty"] = False
                            charts.append(chart)

            except Exception as e:
                traceback.print_exc()
                logger.warning("Failed to generate chart for : %s", e)

        return charts

    def _convert_choice_labels_in_chart(self, chart, model_class):
        """
        Generic method to convert choice field keys to display values in chart data
        """
        try:
            chart_data = chart.get("data", {})
            labels = chart_data.get("labels", [])

            if not labels:
                return chart

            # Try to find which field is being used by checking labelField or title
            label_field = chart_data.get("labelField", "")

            # Convert labelField back to field name (e.g., "Account Type" -> "account_type")
            field_name = label_field.lower().replace(" ", "_")

            # Try to get the field object
            field_obj = None
            try:
                field_obj = model_class._meta.get_field(field_name)
            except Exception:
                # If exact match fails, try to find a field that matches
                for field in model_class._meta.fields:
                    if (
                        field.name.lower() == field_name
                        or field.verbose_name.lower() == label_field.lower()
                    ):
                        field_obj = field
                        field_name = field.name
                        break

            # If we found the field and it has choices, convert the labels
            if field_obj and hasattr(field_obj, "choices") and field_obj.choices:
                new_labels = []
                for label in labels:
                    # Try to find matching choice
                    converted = False
                    for choice_value, choice_label in field_obj.choices:
                        if str(choice_value) == str(label) or choice_value == label:
                            new_labels.append(choice_label)
                            converted = True
                            break

                    if not converted:
                        new_labels.append(label)

                chart_data["labels"] = new_labels

            return chart

        except Exception as e:
            logger.warning("Failed to convert choice labels in chart: %s", e)
            return chart

    def get_date_field(self, model_class):
        """Get the first date field from model"""
        for field in model_class._meta.fields:
            if field.get_internal_type() in ["DateField", "DateTimeField"]:
                return field.name

        return None

    def generate_table_data(self):
        """
        Generate table data for configured models, respecting permissions.

        Iterates configured model info and invokes any provided table functions,
        collecting their results into a list of tables.
        """
        tables = []
        for model_info in self.models:
            try:
                model_class = model_info["model"]
                if not self.has_model_permission(model_class):
                    continue

                table_func = model_info.get("table_func")
                if callable(table_func):
                    table = table_func(self, model_info)
                    if table:
                        tables.append(table)
            except Exception as e:
                traceback.print_exc()
                logger.warning("Failed to generate table for : %s", e)

        return tables

    def build_table_context(
        self,
        model_info,
        title,
        filter_kwargs,
        no_record_msg,
        view_id,
        request=None,
        table_fields=None,
        no_found_img=None,
    ):
        """
        Build table context with pagination for infinite scroll
        """

        try:
            request = getattr(_thread_local, "request", None)
            qs = self.get_queryset(model_info["model"])
            if filter_kwargs:
                qs = qs.filter(**filter_kwargs)

            sort_field = request.GET.get("sort", None) if request else None
            sort_direction = request.GET.get("direction", "asc") if request else "asc"
            if sort_field:
                prefix = "-" if sort_direction == "desc" else ""
                try:
                    qs = qs.order_by(f"{prefix}{sort_field}")
                except Exception:
                    qs = qs.order_by("id")
            else:
                date_field = self.get_date_field(model_info["model"])
                order_field = f"-{date_field}" if date_field else "-pk"
                qs = qs.order_by(order_field)

            page = request.GET.get("page", 1) if request else 1
            paginator = Paginator(qs, 10)
            try:
                page_obj = paginator.get_page(page)
            except Exception:
                page_obj = paginator.get_page(1)

            has_next = page_obj.has_next()
            next_page = page_obj.next_page_number() if has_next else None

            if table_fields is None:
                table_fields_func = model_info.get("table_fields_func")
                if callable(table_fields_func):
                    table_fields = table_fields_func(model_info["model"])
                else:
                    table_fields = None

            if not table_fields:
                return None

            columns = [(f["verbose_name"], f["name"]) for f in table_fields]
            filtered_ids = list(qs.values_list("id", flat=True))

            first_col_field = table_fields[0]["name"] if table_fields else None

            col_attrs = {}
            if first_col_field and hasattr(model_info["model"], "get_detail_url"):
                if self.has_model_permission(model_info["model"]):
                    col_attrs = {
                        first_col_field: {
                            "hx-get": "{get_detail_url}?section=sales",
                            "hx-target": "#mainContent",
                            "hx-swap": "outerHTML",
                            "hx-push-url": "true",
                            "hx-select": "#mainContent",
                            "hx-select-oob": "#sideMenuContainer",
                            "class": "hover:text-primary-600",
                            "style": "cursor:pointer;",
                        }
                    }

            return {
                "id": f"table_{model_info['model']._meta.model_name}_{uuid.uuid4().hex[:8]}",
                "title": title,
                "queryset": page_obj.object_list,
                "columns": columns,
                "view_id": view_id,
                "model_name": model_info["model"]._meta.model_name,
                "model_verbose_name": model_info["model"]._meta.verbose_name_plural,
                "total_records_count": qs.count(),
                "bulk_select_option": False,
                "bulk_export_option": False,
                "bulk_update_option": False,
                "bulk_delete_enabled": False,
                "enable_sorting": True,
                "visible_actions": [],
                "action_method": None,
                "additional_action_button": [],
                "custom_bulk_actions": [],
                "search_url": "",
                "search_params": request.GET.urlencode() if request else "",
                "filter_fields": [],
                "filter_set_class": None,
                "table_class": True,
                "table_width": False,
                "table_height_as_class": "h-[300px]",
                "header_attrs": {},
                "col_attrs": col_attrs,
                "selected_ids": filtered_ids,
                "selected_ids_json": json.dumps(filtered_ids),
                "current_sort": sort_field if request else "",
                "current_direction": sort_direction if request else "",
                "main_url": "",
                "view_type": "dashboard",
                "no_record_section": True,
                "no_record_msg": no_record_msg,
                "no_found_img": no_found_img,
                "no_record_add_button": {},
                "page_obj": page_obj,
                "has_next": has_next,
                "next_page": next_page,
            }
        except Exception as e:
            logger.warning("Failed to generate table for : %s", e)
            return None
