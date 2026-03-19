"""views for horilla_dashboard - helper functions for components"""

# Standard library imports
import json
import logging
from urllib.parse import urlencode

# Third-party imports (Django)
from django.core.paginator import Paginator
from django.db.models import Count

# First-party / Horilla imports
from horilla.apps import apps
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _
from horilla_dashboard.utils import DATE_RANGE_CHOICES, apply_date_range_to_queryset

# Local imports
from horilla_dashboard.views.helper import get_queryset_for_module
from horilla_generics.views import HorillaListView
from horilla_utils.methods import get_section_info_for_model

logger = logging.getLogger(__name__)


def get_kpi_data(component, request):
    """
    Calculate KPI data - always returns count of records.
    """
    model = None
    module_name = component.module.model if component.module else None
    for app_config in apps.get_app_configs():
        try:
            model = apps.get_model(
                app_label=app_config.label, model_name=module_name.lower()
            )
            break
        except LookupError:
            continue

    if not model:
        return None

    try:
        queryset = get_queryset_for_module(request.user, model)

        conditions = component.conditions.all().order_by("sequence")
        queryset = apply_conditions(queryset, conditions)

        value = queryset.count()

        section_info = get_section_info_for_model(model)

        metric_label = (
            f"{component.metric_type.title() if component.metric_type else 'Count'}"
        )

        return {
            "value": float(value),
            "url": section_info["url"],
            "section": section_info["section"],
            "label": f"{metric_label} of {module_name.title()}",
        }
    except Exception:
        return None


def get_report_chart_data(component, request):
    """
    Generate chart data for report-based dashboard components.
    """
    try:
        report = component.reports
        model = None

        module_name = component.module.model if component.module else None

        for app_config in apps.get_app_configs():
            try:
                model = apps.get_model(
                    app_label=app_config.label, model_name=module_name.lower()
                )
                break
            except LookupError:
                continue

        if not model:
            return None

        queryset = get_queryset_for_module(request.user, model)

        if queryset.count() == 0:
            return None

        group_by_field = component.grouping_field

        if not group_by_field:
            return None

        try:
            field_obj = model._meta.get_field(group_by_field)
            is_fk = field_obj.is_relation
        except Exception:
            is_fk = False

        if is_fk:
            chart_data = (
                queryset.values(group_by_field, f"{group_by_field}_id")
                .annotate(value=Count("id"))
                .order_by("-value")
            )
        else:
            chart_data = (
                queryset.values(group_by_field)
                .annotate(value=Count("id"))
                .order_by("-value")
            )

        if not chart_data.exists():
            return None

        labels = []
        data = []
        urls = []

        section_info = get_section_info_for_model(model)

        for item in chart_data:
            label_value = item[group_by_field]

            try:
                field = model._meta.get_field(group_by_field)
                if hasattr(field, "choices") and field.choices:
                    for choice_value, choice_label in field.choices:
                        if choice_value == label_value:
                            label_value = choice_label
                            break
                elif field.is_relation and label_value is not None:
                    related_model = field.related_model
                    try:
                        related_obj = related_model.objects.get(pk=label_value)
                        label_value = str(related_obj)
                    except related_model.DoesNotExist:
                        pass
            except Exception:
                pass

            labels.append(str(label_value) if label_value is not None else "Unknown")
            data.append(float(item["value"]) if item["value"] is not None else 0)

            filter_value = item[group_by_field]
            try:
                field = model._meta.get_field(group_by_field)
                if field.is_relation:
                    filter_value = item.get(f"{group_by_field}_id", filter_value)
            except Exception:
                pass

            query = urlencode(
                {
                    "section": section_info["section"],
                    "apply_filter": "true",
                    "field": group_by_field,
                    "operator": "exact",
                    "value": filter_value,
                }
            )
            urls.append(f"{section_info['url']}?{query}")

        return {
            "title": component.name,
            "type": component.chart_type or "column",
            "data": {
                "labels": labels,
                "data": data,
                "urls": urls,
                "labelField": group_by_field.replace("_", " ").title(),
            },
            "is_from_report": True,  # Flag to identify report-based charts
            "report_name": report.name,
        }

    except Exception as e:
        logger.warning(
            "Failed to generate report chart for component %s: %s", component.id, e
        )
        return None


def get_chart_data(component, request):
    """
    Generate chart data for a dashboard component.
    Returns a dictionary with chart configuration.
    """
    try:
        if component.reports:
            return get_report_chart_data(component, request)
        model = None
        module_name = component.module.model if component.module else None
        for app_config in apps.get_app_configs():
            try:
                model = apps.get_model(
                    app_label=app_config.label, model_name=module_name.lower()
                )
                break
            except LookupError:
                continue

        if not model:
            return None

        queryset = get_queryset_for_module(request.user, model)

        conditions = component.conditions.all().order_by("sequence")
        queryset = apply_conditions(queryset, conditions)

        if queryset.count() == 0:
            return None

        group_by_field = component.grouping_field

        if not group_by_field:
            return None

        try:
            field_obj = model._meta.get_field(group_by_field)
            is_fk = field_obj.is_relation
        except Exception:
            is_fk = False

        if is_fk:
            chart_data = (
                queryset.values(group_by_field, f"{group_by_field}_id")
                .annotate(value=Count("id"))
                .order_by("-value")
            )
        else:
            chart_data = (
                queryset.values(group_by_field)
                .annotate(value=Count("id"))
                .order_by("-value")
            )

        if not chart_data.exists():
            return None

        labels = []
        data = []
        urls = []

        section_info = get_section_info_for_model(model)

        for item in chart_data:
            label_value = item[group_by_field]

            try:
                field = model._meta.get_field(group_by_field)
                if hasattr(field, "choices") and field.choices:
                    for choice_value, choice_label in field.choices:
                        if choice_value == label_value:
                            label_value = choice_label
                            break
            except Exception:
                pass

            labels.append(str(label_value) if label_value is not None else "Unknown")
            data.append(float(item["value"]) if item["value"] is not None else 0)

            filter_value = item[group_by_field]
            try:
                field = model._meta.get_field(group_by_field)
                if field.is_relation:
                    filter_value = item.get(f"{group_by_field}_id", filter_value)
            except Exception:
                pass

            query = urlencode(
                {
                    "section": section_info["section"],
                    "apply_filter": "true",
                    "field": group_by_field,
                    "operator": "exact",
                    "value": filter_value,
                }
            )
            urls.append(f"{section_info['url']}?{query}")

        return {
            "title": component.name,
            "type": component.chart_type or "column",
            "data": {
                "labels": labels,
                "data": data,
                "urls": urls,
                "labelField": group_by_field.replace("_", " ").title(),
            },
            "is_report": component.reports is not None,
        }

    except Exception as e:
        logger.warning("Failed to generate chart for component %s: %s", component.id, e)
        return None


def apply_conditions(queryset, conditions):
    """Apply filter conditions to a queryset with proper type handling."""

    for condition in conditions:
        field = condition.field
        operator = condition.operator
        value = condition.value

        if not value and operator not in ["is_null", "is_not_null"]:
            continue

        try:
            model = queryset.model
            field_obj = model._meta.get_field(field)

            converted_value = value
            if hasattr(field_obj, "get_internal_type"):
                field_type = field_obj.get_internal_type()

                if field_type in [
                    "IntegerField",
                    "BigIntegerField",
                    "SmallIntegerField",
                    "PositiveIntegerField",
                    "PositiveSmallIntegerField",
                    "DecimalField",
                    "FloatField",
                ]:
                    try:
                        if field_type in ["DecimalField", "FloatField"]:
                            converted_value = float(value)
                        else:
                            converted_value = int(value)
                    except (ValueError, TypeError):
                        logger.warning(
                            "Could not convert value '%s' to numeric for field '%s'",
                            value,
                            field,
                        )
                        continue

                elif field_type == "BooleanField":
                    if str(value).lower() in ["true", "1", "yes"]:
                        converted_value = True
                    elif str(value).lower() in ["false", "0", "no"]:
                        converted_value = False
                    else:
                        logger.warning(
                            "Invalid boolean value '%s' for field '%s'",
                            value,
                            field,
                        )
                        continue

                elif field_type == "ForeignKey":
                    try:
                        converted_value = int(value)
                    except (ValueError, TypeError):
                        logger.warning(
                            "Could not convert FK value '%s' to int for field '%s'",
                            value,
                            field,
                        )
                        continue

            if operator in ["equals", "exact"]:
                queryset = queryset.filter(**{field: converted_value})

            elif operator == "not_equals":
                queryset = queryset.exclude(**{field: converted_value})

            elif operator == "greater_than":
                queryset = queryset.filter(**{f"{field}__gt": converted_value})

            elif operator == "less_than":
                queryset = queryset.filter(**{f"{field}__lt": converted_value})

            elif operator == "greater_equal":
                queryset = queryset.filter(**{f"{field}__gte": converted_value})

            elif operator == "less_equal":
                queryset = queryset.filter(**{f"{field}__lte": converted_value})

            elif operator == "contains":
                queryset = queryset.filter(**{f"{field}__icontains": value})

            elif operator == "not_contains":
                queryset = queryset.exclude(**{f"{field}__icontains": value})

            elif operator == "starts_with":
                queryset = queryset.filter(**{f"{field}__istartswith": value})

            elif operator == "ends_with":
                queryset = queryset.filter(**{f"{field}__iendswith": value})

            elif operator == "is_null":
                queryset = queryset.filter(**{f"{field}__isnull": True})

            elif operator == "is_not_null":
                queryset = queryset.filter(**{f"{field}__isnull": False})

            elif operator == "in":
                values = [v.strip() for v in str(value).split(",")]
                queryset = queryset.filter(**{f"{field}__in": values})

            elif operator == "not_in":
                values = [v.strip() for v in str(value).split(",")]
                queryset = queryset.exclude(**{f"{field}__in": values})

        except Exception as e:
            logger.error(
                "Error applying condition %s %s %s: %s", field, operator, value, e
            )
            continue

    return queryset


def get_table_data(component, request):
    """
    Generate table data and context for a dashboard component using HorillaListView.
    """
    model = None

    module_name = component.module.model if component.module else None
    for app_config in apps.get_app_configs():
        try:
            model = apps.get_model(
                app_label=app_config.label, model_name=module_name.lower()
            )
            break
        except LookupError:
            continue

    if not model:
        return None, {}

    queryset = get_queryset_for_module(request.user, model)
    conditions = component.conditions.all().order_by("sequence")
    queryset = apply_conditions(queryset, conditions)

    date_range = request.GET.get("date_range")
    if date_range and (
        str(date_range) in [str(d) for d in DATE_RANGE_CHOICES]
        or date_range == "custom"
    ):
        date_from = request.GET.get("date_from") if date_range == "custom" else None
        date_to = request.GET.get("date_to") if date_range == "custom" else None
        queryset = apply_date_range_to_queryset(
            queryset, model, date_range, date_from=date_from, date_to=date_to
        )

    sort_field = request.GET.get("sort", None)
    sort_direction = request.GET.get("direction", "asc")
    if sort_field:
        prefix = "-" if sort_direction == "desc" else ""
        try:
            queryset = queryset.order_by(f"{prefix}{sort_field}")
        except Exception:
            queryset = queryset.order_by("id")
    else:
        queryset = queryset.order_by("id")

    paginator = Paginator(queryset, 10)
    page = request.GET.get("page", 1)
    page_obj = paginator.get_page(page)
    has_next = page_obj.has_next()
    next_page = page_obj.next_page_number() if has_next else None

    columns = []
    if component.columns:
        try:
            if isinstance(component.columns, str):
                if component.columns.startswith("["):
                    selected_columns = json.loads(component.columns)
                else:
                    selected_columns = [
                        col.strip()
                        for col in component.columns.split(",")
                        if col.strip()
                    ]
            else:
                selected_columns = component.columns
        except Exception:
            selected_columns = []
    else:
        selected_columns = []
        for field in model._meta.get_fields()[:5]:
            if field.concrete and not field.is_relation:
                selected_columns.append(field.name)

    for column in selected_columns:
        try:
            field = model._meta.get_field(column)
            verbose_name = field.verbose_name or column.replace("_", " ").title()
            if hasattr(field, "choices") and field.choices:
                columns.append((verbose_name, f"get_{column}_display"))
            else:
                columns.append((verbose_name, column))
        except Exception:
            continue

    if not columns:
        for field in model._meta.get_fields()[:3]:
            if field.concrete and not field.is_relation:
                columns.append(
                    (
                        field.verbose_name or field.name.replace("_", " ").title(),
                        field.name,
                    )
                )

    query_params = request.GET.urlencode()

    table_data_url = reverse_lazy(
        "horilla_dashboard:component_table_data",
        kwargs={"component_id": component.id},
    )

    list_view = HorillaListView(
        model=model,
        view_id=f"dashboard_component_{component.id}",
        search_url=table_data_url,
        main_url=reverse_lazy(
            "horilla_dashboard:dashboard_detail_view",
            kwargs={"pk": component.dashboard_id},
        ),
        table_width=False,
        filterset_class=getattr(model, "FilterSet", None),
        columns=columns,
    )
    list_view.request = request
    list_view.table_width = False
    list_view.bulk_select_option = True
    list_view.bulk_export_option = True
    list_view.bulk_update_option = False
    list_view.bulk_delete_enabled = False
    list_view.list_column_visibility = False
    list_view.table_height_as_class = "h-[300px]"
    list_view.object_list = page_obj.object_list
    list_view.enable_sorting = True
    list_view.has_next = has_next
    list_view.next_page = next_page
    list_view.search_params = query_params
    list_view.model_verbose_name = model._meta.verbose_name_plural
    list_view.total_records_count = queryset.count()
    list_view.selected_ids_json = json.dumps([])
    list_view.list_column_visibility = False

    filtered_ids = list(queryset.values_list("id", flat=True))
    list_view.selected_ids_json = json.dumps(filtered_ids)

    first_col_field = None
    if columns:
        first_col_field = columns[0][1]
        if first_col_field.startswith("get_") and first_col_field.endswith("_display"):
            first_col_field = first_col_field[4:-8]

    first_obj = page_obj.object_list[0] if page_obj.object_list else None
    col_attrs = {}

    if first_col_field and hasattr(model, "get_detail_url") and first_obj:
        if request.user.has_perm(
            f"{model._meta.app_label}.view_{model._meta.model_name}"
        ):
            section_info = get_section_info_for_model(model)
            section = section_info["section"]

            col_attrs[first_col_field] = {
                "hx-get": f"{first_obj.get_detail_url()}?section={section}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select": "#mainContent",
                "hx-select-oob": "#sideMenuContainer",
                "class": "hover:text-primary-600",
                "style": "cursor:pointer;",
            }

    context = list_view.get_context_data(object_list=page_obj.object_list)

    context.update(
        {
            "no_record_msg": f"No {model._meta.verbose_name_plural} found matching the specified criteria.",
            "header_attrs": {},
            "col_attrs": col_attrs,
            "visible_actions": [],
            "custom_bulk_actions": [],
            "additional_action_button": [],
            "filter_set_class": None,
            "filter_fields": list_view._get_model_fields(),
            "total_records_count": queryset.count(),
            "selected_ids": filtered_ids,
            "selected_ids_json": json.dumps(filtered_ids),
            "queryset": page_obj.object_list,
            "page_obj": page_obj,
            "search_url": table_data_url,
            "search_params": query_params,
            "has_next": has_next,
            "next_page": next_page,
            "component": component,
            "view_id": f"dashboard_component_{component.id}",
            "app_label": model._meta.app_label,
            "model_name": model._meta.model_name,
            "model_verbose_name": model._meta.verbose_name_plural,
        }
    )

    return model, context
