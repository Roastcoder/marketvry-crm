"""Views for filtering and listing report data."""

import logging
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import ForeignKey, Q
from django.views import View

from horilla.shortcuts import render

# First-party / Horilla imports
from horilla.urls import reverse_lazy
from horilla.utils.choices import TABLE_FALLBACK_FIELD_TYPES
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla_generics.views import HorillaListView
from horilla_reports.models import Report
from horilla_utils.methods import get_section_info_for_model

from .toolkit.report_helper import create_temp_report_with_preview

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["horilla_reports.view_report", "horilla_reports.view_own_report"]
    ),
    name="dispatch",
)
class ReportDetailFilteredView(LoginRequiredMixin, View):
    """View for displaying filtered report data with dynamic column and row grouping."""

    def col_attrs(self):
        """Define column attributes for clickable rows in the report list view."""
        query_params = {}
        pk = self.kwargs.get("pk")
        report = Report.objects.get(pk=pk)

        model_class = report.model_class
        section = get_section_info_for_model(model_class)
        section_value = section["section"]
        query_params["section"] = section_value
        query_string = urlencode(query_params)
        attrs = {}

        if self.request.user.has_perm("horilla_reports.view_report"):
            attrs = {
                "hx-get": f"{{get_detail_url}}?{query_string}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-on:click": "closeContentModal()",
                "hx-select": "#mainContent",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }

        columns_with_attrs = []

        for col in report.selected_columns_list:
            columns_with_attrs.append({col: {**attrs}})

        return columns_with_attrs

    def get(self, request, pk, *args, **kwargs):
        """Handle GET request to render the report detail or preview."""
        # Get the report
        try:
            report = Report.objects.get(pk=pk)
        except Report.DoesNotExist:
            return render(request, "list_view.html")

        # Check if we have preview data in session
        session_key = f"report_preview_{report.pk}"
        preview_data = request.session.get(session_key, {})

        # Create a temporary report object with preview data
        temp_report = self.create_temp_report(report, preview_data)

        model_class = temp_report.model_class
        queryset = model_class.objects.all()

        # Apply original report filters using temp_report
        filters = temp_report.filters_dict
        if filters:
            try:
                # Use the same filter logic as ReportDetailView
                query = None
                for index, (field_name, filter_data) in enumerate(filters.items()):
                    if not filter_data.get("value"):
                        continue  # Skip empty filters
                    operator = filter_data.get("operator", "exact")
                    value = filter_data.get("value")
                    logic = (
                        filter_data.get("logic", "and") if index > 0 else "and"
                    )  # Default to AND for first filter

                    # Use original_field instead of field_name
                    actual_field = filter_data.get("original_field", field_name)

                    # Construct filter kwargs
                    filter_kwargs = {}
                    if operator == "exact":
                        filter_kwargs[actual_field] = value
                    elif operator == "icontains":
                        filter_kwargs[f"{actual_field}__icontains"] = value
                    elif operator == "gt":
                        filter_kwargs[f"{actual_field}__gt"] = value
                    elif operator == "lt":
                        filter_kwargs[f"{actual_field}__lt"] = value
                    elif operator == "gte":
                        filter_kwargs[f"{actual_field}__gte"] = value
                    elif operator == "lte":
                        filter_kwargs[f"{actual_field}__lte"] = value

                    # Combine filters with AND or OR
                    if not filter_kwargs:
                        continue
                    current_query = Q(**filter_kwargs)

                    if query is None:
                        query = current_query
                    elif logic == "or":
                        query |= current_query
                    else:  # logic == 'and'
                        query &= current_query

                if query:
                    queryset = queryset.filter(query)
            except Exception as e:
                logger.error("Filter Error in ReportDetailFilteredView: %s", e)
                queryset = model_class.objects.none()

        row_group1 = request.GET.get("row_group1")
        row_group2 = request.GET.get("row_group2")
        row_group3 = request.GET.get("row_group3")
        col = request.GET.get("col")
        col1 = request.GET.get("col1")
        col2 = request.GET.get("col2")
        # simple_aggregate = request.GET.get("simple_aggregate")

        # Use temp_report instead of report for row_groups and column_groups
        row_fields = temp_report.row_groups_list
        col_fields = temp_report.column_groups_list
        filter_kwargs = {}

        def get_dynamic_lookup_fields(related_model, original_field_name):
            """
            Dynamically determine lookup fields for a related model.
            Returns a list of field names to try for lookups.
            """
            lookup_fields = []

            # Get all fields from the related model
            for field in related_model._meta.get_fields():
                if hasattr(field, "name"):
                    field_name = field.name

                    # Prioritize common display fields
                    if field_name in ["name", "title", "display_name", "label"]:
                        lookup_fields.insert(0, field_name)  # Add to front
                    # Include string/char fields that might be used for display
                    elif (
                        hasattr(field, "get_internal_type")
                        and field.get_internal_type() in TABLE_FALLBACK_FIELD_TYPES[:2]
                    ):  # [CharField, TextField]
                        lookup_fields.append(field_name)

            # Add the original field name as fallback
            if original_field_name not in lookup_fields:
                lookup_fields.append(original_field_name)

            # Add 'pk' and 'id' as final fallbacks
            if "pk" not in lookup_fields:
                lookup_fields.append("pk")
            if "id" not in lookup_fields:
                lookup_fields.append("id")

            return lookup_fields

        def get_filter_value(field_name, value, model):
            """Convert a filter string/value into an actual model field value for lookup."""
            if not value or not field_name:
                return None
            try:
                field = model._meta.get_field(field_name)
                if isinstance(field, ForeignKey):
                    if isinstance(value, str) and "||" in value:
                        parts = value.split("||")
                        if len(parts) == 2:
                            try:
                                pk_value = int(parts[1])
                                related_model = field.related_model
                                try:
                                    return related_model.objects.get(pk=pk_value)
                                except related_model.DoesNotExist:
                                    logger.warning(
                                        "Related object not found with pk=%s", pk_value
                                    )
                                    return None
                            except (ValueError, TypeError):
                                value = parts[0]  # Use display part for lookup

                    related_model = field.related_model
                    lookup_fields = get_dynamic_lookup_fields(related_model, field_name)

                    for lookup_field in lookup_fields:
                        try:
                            related_obj = related_model.objects.get(
                                **{lookup_field: value}
                            )
                            return related_obj
                        except related_model.DoesNotExist:
                            continue
                        except AttributeError:
                            continue
                        except Exception as e:
                            logger.error("Error trying lookup %s: %s", lookup_field, e)
                            continue

                    # If exact match fails, try case-insensitive for string fields
                    for lookup_field in lookup_fields:
                        try:
                            field_obj = related_model._meta.get_field(lookup_field)
                            if (
                                hasattr(field_obj, "get_internal_type")
                                and field_obj.get_internal_type()
                                in TABLE_FALLBACK_FIELD_TYPES[:2]
                            ):  # [CharField, TextField]
                                related_obj = related_model.objects.get(
                                    **{f"{lookup_field}__iexact": value}
                                )
                                return related_obj
                        except (related_model.DoesNotExist, AttributeError, Exception):
                            continue
                    return None
                if field.choices:
                    # Check if value is a composite key for choices
                    if isinstance(value, str) and "||" in value:
                        parts = value.split("||")
                        value = parts[0]  # Use display part

                    choice_map = {
                        display.lower(): value for value, display in field.choices
                    }
                    normalized_value = value.lower()
                    if normalized_value in choice_map:
                        return choice_map[normalized_value]
                    return value  # Fallback to original value if no match
                # else:
                # For non-FK fields, check if it's a composite key and extract the value
                if isinstance(value, str) and "||" in value:
                    parts = value.split("||")
                    # For non-FK fields, try to convert to appropriate type
                    try:
                        if hasattr(field, "get_internal_type"):
                            field_type = field.get_internal_type()
                            if field_type in [
                                "IntegerField",
                                "BigIntegerField",
                                "SmallIntegerField",
                            ]:
                                return int(parts[1])
                            if field_type in ["FloatField", "DecimalField"]:
                                return float(parts[1])
                    except (ValueError, TypeError, IndexError):
                        pass
                    # If conversion fails, use the display part
                    value = parts[0]
                return value
            except Exception as e:
                logger.error(
                    "Error resolving filter value for %s=%s: %s", field_name, value, e
                )
                return None

        if row_group1 and row_fields:
            filter_value = get_filter_value(row_fields[0], row_group1, model_class)
            if filter_value is not None:
                filter_kwargs[row_fields[0]] = filter_value
        if row_group2 and len(row_fields) > 1:
            filter_value = get_filter_value(row_fields[1], row_group2, model_class)
            if filter_value is not None:
                filter_kwargs[row_fields[1]] = filter_value
        if row_group3 and len(row_fields) > 2:
            filter_value = get_filter_value(row_fields[2], row_group3, model_class)
            if filter_value is not None:
                filter_kwargs[row_fields[2]] = filter_value
        if col and col_fields:
            filter_value = get_filter_value(col_fields[0], col, model_class)
            if filter_value is not None:
                filter_kwargs[col_fields[0]] = filter_value
        if col1 and col2 and len(col_fields) > 1:
            filter_value1 = get_filter_value(col_fields[0], col1, model_class)
            filter_value2 = get_filter_value(col_fields[1], col2, model_class)
            if filter_value1 is not None:
                filter_kwargs[col_fields[0]] = filter_value1
            if filter_value2 is not None:
                filter_kwargs[col_fields[1]] = filter_value2
        # if simple_aggregate and temp_report.aggregate_columns_dict.get('field'):
        #     filter_kwargs[temp_report.aggregate_columns_dict['field']] = simple_aggregate

        if filter_kwargs:
            try:
                queryset = queryset.filter(**filter_kwargs)
            except Exception as e:
                logger.error("Filter Error: %s", e)
                queryset = model_class.objects.none()

        columns = []
        for col in temp_report.selected_columns_list:
            field = model_class._meta.get_field(col)
            verbose_name = field.verbose_name.title()
            if field.choices:
                columns.append((verbose_name, f"get_{col}_display"))
            else:
                columns.append((verbose_name, col))

        list_view = HorillaListView(
            model=model_class,
            view_id="report-details",
            search_url=reverse_lazy(
                "horilla_reports:report_detail_filtered", kwargs={"pk": report.pk}
            ),
            main_url=reverse_lazy(
                "horilla_reports:report_detail_filtered", kwargs={"pk": report.pk}
            ),
            table_width=False,
            columns=columns,
        )
        list_view.request = request
        list_view.table_width = False
        list_view.bulk_select_option = False
        list_view.paginate_by = 10
        list_view.list_column_visibility = False
        list_view.table_height_as_class = "h-[200px]"
        if hasattr(report.model_class, "get_detail_url"):
            list_view.col_attrs = self.col_attrs()
        sort_field = self.request.GET.get("sort")
        sort_direction = self.request.GET.get("direction", "asc")
        if sort_field:
            queryset = list_view._apply_sorting(queryset, sort_field, sort_direction)
        else:
            queryset = queryset.order_by("-id")
        list_view.queryset = queryset  # Set object_list to avoid AttributeError
        context = list_view.get_context_data(object_list=queryset)

        # Add no_record_msg if queryset is empty
        if not queryset.exists():
            context["no_record_msg"] = "No records found"

        # Render only the list_view.html template
        return render(request, "list_view.html", context)

    def create_temp_report(self, original_report, preview_data):
        """Create a temporary report object with preview data (same as ReportDetailView)."""
        return create_temp_report_with_preview(original_report, preview_data)
