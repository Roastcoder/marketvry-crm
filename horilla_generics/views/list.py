"""
A highly customizable ListView for Horilla that supports dynamic column generation, filtering, searching, and action handling with infinite scrolling pagination.
This view can be extended to create specific list views for different models, and includes features like pinned views, recently viewed/created/modified filters, saved filter lists.
"""

# Standard library
import json
import logging
from functools import reduce
from operator import or_

# Django / third-party imports
from django.db.models import Case, Q, When
from django.utils.dateparse import parse_date, parse_datetime, parse_time
from django.views.generic import ListView

from horilla.db.models.fields import GenericForeignKey
from horilla.http import HttpResponse, QueryDict

# First-party (Horilla)
from horilla.shortcuts import render
from horilla.utils import translation
from horilla_core.models import PinnedView, RecentlyViewed, SavedFilterList
from horilla_core.utils import filter_hidden_fields, get_editable_fields
from horilla_generics.mixins import HorillaListViewMixin
from horilla_generics.views.toolkit import (
    HorillaBulkDeleteMixin,
    HorillaBulkExportMixin,
    HorillaBulkUpdateMixin,
    quick_filter,
)

logger = logging.getLogger(__name__)


class HorillaListView(HorillaListViewMixin, ListView):
    """
    A customizable ListView that provides automatic column generation,
    filtering, searching, and action handling with infinite scrolling pagination.
    """

    template_name = "list_view.html"
    context_object_name = "queryset"
    columns = []
    actions = []
    view_id = ""
    action_method = ""
    exclude_columns = []
    default_sort_field = None
    default_sort_direction = "asc"
    sort_by_mapping = []
    paginate_by = 100
    page_kwarg = "page"
    main_url: str = ""
    search_url: str = ""
    filterset_class = None
    filter_url_push = True
    max_visible_actions = 4
    bulk_update_fields = []
    bulk_update_two_column = False
    raw_attrs: list = []
    number_of_recent_view = 20
    bulk_delete_enabled = True
    header_attrs = []
    col_attrs = []
    bulk_select_option = True
    no_record_section = True
    no_record_add_button: dict = None
    no_record_msg: str = None
    table_width = True
    table_class = True
    table_height_as_class = ""
    bulk_update_option = True
    store_ordered_ids = False
    save_to_list_option = True
    enable_sorting = True
    custom_bulk_actions = []
    bulk_export_option = True
    additional_action_button = []
    list_column_visibility = True
    owner_filtration = True
    sorting_target = None
    exclude_columns_from_sorting = []
    no_found_img: str = ""
    enable_quick_filters = False  # Set to True in child classes to enable
    exclude_quick_filter_fields = []  # Fields to exclude from quick filters

    def __init__(self, **kwargs):
        self._model_fields_cache = None
        super().__init__(**kwargs)
        if self.store_ordered_ids:
            self.ordered_ids_key = f"ordered_ids_{self.model.__name__.lower()}"
        self.kwargs = kwargs

        if self.columns:
            resolved_columns = []
            instance = self.model()

            # Force English when resolving column names
            with translation.override("en"):
                for col in self.columns:
                    if isinstance(col, (tuple, list)) and len(col) >= 2:
                        resolved_columns.append((str(col[0]), str(col[1])))
                    elif isinstance(col, str):
                        try:
                            field = instance._meta.get_field(col)
                            verbose_name = str(field.verbose_name)
                            resolved_columns.append((verbose_name, col))
                        except Exception:
                            resolved_columns.append(
                                (col.replace("_", " ").title(), col)
                            )
                    else:
                        resolved_columns.append((str(col), str(col)))

            self.columns = resolved_columns

    def get_default_view_type(self):
        """Return the pinned view_type if available, else 'all'."""
        pinned_view = PinnedView.all_objects.filter(
            user=self.request.user, model_name=self.model.__name__
        ).first()
        return pinned_view.view_type if pinned_view else "all"

    def get_queryset(self):
        """Get filtered queryset based on search, filter, or view type parameters."""

        queryset = super().get_queryset()
        queryset = quick_filter.apply_quick_filters(queryset, self)
        view_type = self.request.GET.get("view_type") or self.get_default_view_type()

        is_bulk_operation = (
            (
                self.request.method == "POST"
                and self.request.POST.get("action")
                in [
                    "bulk_delete",
                    "delete_item_with_dependencies",
                    "delete_all_dependencies",
                ]
            )
            or self.request.POST.get("bulk_delete_form") == "true"
            or self.request.POST.get("soft_delete_form") == "true"
        )

        if is_bulk_operation:
            view_type = self.request.GET.get("view_type")
            if not view_type:
                view_type = "all"
        else:
            view_type = (
                self.request.GET.get("view_type") or self.get_default_view_type()
            )

        if view_type == "recently_viewed":
            recently_viewed_items = RecentlyViewed.objects.get_recently_viewed(
                user=self.request.user, model_class=self.model
            )
            pks = [item.pk for item in recently_viewed_items if item]
            queryset = queryset.filter(pk__in=pks)

        elif view_type in ("recently_created", "recently_modified"):
            sort_field = (
                "-created_at" if view_type == "recently_created" else "-updated_at"
            )
            recent_queryset = queryset.order_by(sort_field)[:20]
            recent_ids = list(recent_queryset.values_list("pk", flat=True))
            queryset = queryset.filter(pk__in=recent_ids)

        elif view_type.startswith("saved_list_"):
            saved_list_id = view_type.replace("saved_list_", "")
            try:
                saved_list = (
                    SavedFilterList.all_objects.filter(id=saved_list_id)
                    .filter(Q(user=self.request.user) | Q(is_public=True))
                    .first()
                )
                if saved_list:
                    filter_params = saved_list.get_filter_params()
                    merged_params = QueryDict(mutable=True)
                    for key, values in filter_params.items():
                        for value in values:
                            merged_params.appendlist(key, value)

                    search_keys = [
                        "field",
                        "operator",
                        "value",
                        "start_value",
                        "end_value",
                        "search",
                    ]
                    for key, values in self.request.GET.lists():
                        if key in search_keys:
                            for value in values:
                                merged_params.appendlist(key, value)

                    if self.filterset_class:
                        self.filterset = self.filterset_class(
                            merged_params, queryset=queryset, request=self.request
                        )
                        queryset = self.filterset.filter_queryset(queryset)
            except Exception:
                pass

        if self.filterset_class and not (
            view_type.startswith("saved_list_") and getattr(self, "filterset", None)
        ):
            self.filterset = self.filterset_class(
                self.request.GET, queryset=queryset, request=self.request
            )
            queryset = self.filterset.filter_queryset(queryset)

        sort_field = self.request.GET.get("sort")
        sort_direction = self.request.GET.get("direction", self.default_sort_direction)

        if view_type == "recently_viewed" and not sort_field and "pks" in locals():
            preserved_order = Case(
                *[When(pk=pk, then=pos) for pos, pk in enumerate(pks)]
            )
            queryset = queryset.order_by(preserved_order)
        elif sort_field:
            queryset = self._apply_sorting(queryset, sort_field, sort_direction)
        elif view_type == "recently_created":
            queryset = queryset.order_by("-created_at")
        elif view_type == "recently_modified":
            queryset = queryset.order_by("-updated_at")
        elif self.default_sort_field:
            order_prefix = "-" if self.default_sort_direction == "desc" else ""
            queryset = queryset.order_by(f"{order_prefix}{self.default_sort_field}")
        else:
            queryset = queryset.order_by("-id")

        if self.store_ordered_ids:
            ordered_ids = list(queryset.values_list("pk", flat=True))
            self.request.session[self.ordered_ids_key] = ordered_ids

        if self.owner_filtration:
            user = self.request.user
            app_label = self.model._meta.app_label
            model_name = self.model._meta.model_name
            view_perm = f"{app_label}.view_{model_name}"
            view_own_perm = f"{app_label}.view_own_{model_name}"

            if user.has_perm(view_perm):
                return queryset

            if user.has_perm(view_own_perm):
                owner_fields = getattr(self.model, "OWNER_FIELDS", None)

                if owner_fields:
                    query = reduce(
                        or_,
                        (Q(**{field_name: user}) for field_name in owner_fields),
                        Q(),
                    )
                    return queryset.filter(query).distinct()

            return queryset.none()
        return queryset.distinct()

    def _apply_sorting(self, queryset, field, direction):
        """Fast sorting: uses DB fields or mapped aliases only."""

        if not field:
            return queryset

        if field.startswith("get_") and field.endswith("_display"):
            field = field[4:-8]

        mapped_field = next(
            (
                item[1]
                for item in getattr(self, "sort_by_mapping", [])
                if item[0] == field
            ),
            field,
        )
        model_class = queryset.model
        if not hasattr(model_class, mapped_field):
            return queryset

        attr = getattr(model_class, mapped_field)
        if callable(attr) or isinstance(attr, property):
            return queryset

        # Check if the field is a GenericForeignKey
        try:
            field_obj = model_class._meta.get_field(mapped_field)

            if isinstance(field_obj, GenericForeignKey):
                # Sort by content_type_id and then object_id
                ct_field = field_obj.ct_field + "_id"  # Usually 'content_type_id'
                fk_field = field_obj.fk_field  # Usually 'object_id'

                if direction == "desc":
                    return queryset.order_by(f"-{ct_field}", f"-{fk_field}")
                # else:
                return queryset.order_by(ct_field, fk_field)
        except Exception:
            pass

        order_field = f"-{mapped_field}" if direction == "desc" else mapped_field

        try:
            return queryset.order_by(order_field)
        except Exception as e:

            logger.warning("Could not sort by field '%s': %s", mapped_field, str(e))
            return queryset

    def render_to_response(self, context, **response_kwargs):
        """Override to handle different types of requests appropriately."""
        is_htmx = self.request.headers.get("HX-Request") == "true"
        context["request_params"] = self.request.GET.copy()

        if is_htmx:
            return render(self.request, "list_view.html", context)

        return super().render_to_response(context, **response_kwargs)

    def handle_custom_bulk_action(self, action, record_ids):
        """Handle custom bulk actions based on their configuration."""
        try:
            if action.get("handler"):
                # Call custom handler function if provided
                handler = getattr(self, action["handler"], None)
                if callable(handler):
                    return handler(record_ids, self.request)
                # else:
                return HttpResponse(
                    f"Handler {action['handler']} not found.", status=500
                )

            # Default behavior: HTMX POST request
            url = action.get("url")
            if not url:
                return HttpResponse(
                    f"No URL provided for action {action['name']}.", status=400
                )

            context = self.get_context_data()
            context.update(
                {
                    "selected_ids": record_ids,
                    "selected_ids_json": json.dumps(record_ids),
                    "action_name": action["name"],
                }
            )

            # Prepare HTMX attributes
            hx_attrs = {
                (
                    "hx-post"
                    if action.get("method", "POST").upper() == "POST"
                    else "hx-get"
                ): url,
                "hx-target": action.get("target", "#modalBox"),
                "hx-swap": action.get("swap", "innerHTML"),
                "hx-vals": f'js:{{"selected_ids": JSON.stringify(selectedRecordIds("{self.view_id}")), "action": "{action["name"]}"}}',
            }
            if action.get("after_request"):
                hx_attrs["hx-on::after-request"] = action["after_request"]

            context["hx_attrs"] = hx_attrs
            return render(self.request, "list_view.html", context)

        except Exception as e:
            logger.error("Custom  action %s failed: %s", action["name"], str(e))
            return HttpResponse(f"Action {action['name']} failed: {str(e)}", status=500)

    def post(self, request, *args, **kwargs):
        """
        Handle POST requests for exporting data.
        """

        record_ids = request.POST.get("record_ids")
        columns = [
            value
            for key, value in request.POST.items()
            if key.startswith("expo_avail_") or key.startswith("expo_add_")
        ]
        action = request.POST.get("action")
        # columns = request.POST.getlist("export_columns")
        export_format = request.POST.get("export_format")
        delete_type = request.POST.get("delete_type")

        # Handle custom bulk actions
        if action in [bulk["name"] for bulk in self.custom_bulk_actions]:
            try:
                record_ids = json.loads(record_ids) if record_ids else []
                bulk_action = next(
                    bulk for bulk in self.custom_bulk_actions if bulk["name"] == action
                )
                return self.handle_custom_bulk_action(bulk_action, record_ids)
            except json.JSONDecodeError as e:
                logger.error("Error decoding record_ids JSON: %s", str(e))
                return HttpResponse("Invalid JSON data for record_ids", status=400)

        if action in [
            additional["name"] for additional in self.additional_action_button
        ]:
            try:
                record_ids = json.loads(record_ids) if record_ids else []
                bulk_action = next(
                    additional
                    for additional in self.additional_action_button
                    if additional["name"] == action
                )
                return self.handle_custom_bulk_action(bulk_action, record_ids)
            except json.JSONDecodeError as e:
                logger.error("Error decoding record_ids JSON: %s", str(e))
                return HttpResponse("Invalid JSON data for record_ids", status=400)

        # Delegate bulk delete–related handling to helper
        bulk_delete_response = HorillaBulkDeleteMixin.handle_bulk_delete_post(
            self,
            request=request,
            action=action,
            record_ids=record_ids,
            delete_type=delete_type,
        )
        if bulk_delete_response is not None:
            return bulk_delete_response

        bulk_update_response = HorillaBulkUpdateMixin.handle_bulk_update_post(
            self,
            request=request,
            record_ids=record_ids,
            columns=columns,
        )
        if bulk_update_response is not None:
            return bulk_update_response

        export_response = HorillaBulkExportMixin.handle_bulk_export_post(
            self,
            record_ids=record_ids,
            columns=columns,
            export_format=export_format,
        )
        if export_response is not None:
            return export_response

        # Delegate quick filter add/remove actions to helper
        quick_filter_response = quick_filter.handle_quick_filter_post(
            request, action, self
        )
        if quick_filter_response is not None:
            return quick_filter_response

        return HttpResponse("Invalid request: Missing required fields", status=400)

    def get(self, request, *args, **kwargs):
        """
        Handle GET requests and ensure an HttpResponse is returned.
        """

        self.object_list = self.get_queryset()
        context = self.get_context_data()

        # Handle filter row addition
        if request.GET.get("add_filter_row") == "true":

            curr_row_id = int(request.GET.get("row_id"))
            new_row_id = curr_row_id + 1
            filter_rows = [{"row_id": new_row_id}]
            context["filter_rows"] = filter_rows
            return render(request, "partials/filter_row.html", context)

        if "remove_filter" in request.GET:
            return self.handle_remove_filter(request)

        if request.GET.get("clear_all_filters") == "true":
            has_search = request.GET.get("search", "").strip()
            has_other_ops = request.GET.get("apply_filter") or request.GET.get(
                "remove_filter"
            )
            if not has_search and not has_other_ops:
                return self.handle_clear_all_filters(request)

        if request.GET.get("remove_filter_field") == "true":
            return HttpResponse("")

        if request.headers.get("HX-Request") == "true":
            # Delegate quick filter-related HTMX requests to helper
            quick_filter_response = quick_filter.handle_quick_filter_get(request, self)
            if quick_filter_response is not None:
                return quick_filter_response

            if request.GET.get("field_change") and not request.GET.get(
                "operator_change"
            ):
                field_name = request.GET.get("field")
                row_id = request.GET.get("row_id")
                return self.handle_field_change(request, field_name, row_id)

            if request.GET.get("operator_change"):
                field_name = request.GET.get("field")
                operator = request.GET.get("operator")
                row_id = request.GET.get("row_id")
                return self.handle_operator_change(
                    request, field_name, operator, row_id
                )

            return render(request, self.template_name, context)

        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        """Enhance context with column and filtering information."""
        context = super().get_context_data(**kwargs)
        if self.store_ordered_ids:
            context["ordered_ids_key"] = self.ordered_ids_key
            context["ordered_ids"] = self.request.session.get(self.ordered_ids_key, [])

        filter_fields = self._get_model_fields(include_properties=False)
        export_additional_fields = self._get_model_fields(
            include_properties=True, for_export=True
        )

        available_column_names = {col[1] for col in self._get_columns()}
        export_additional_fields = [
            f
            for f in export_additional_fields
            if f["name"] not in available_column_names
        ]

        additional_field_names = [f["name"] for f in export_additional_fields]
        visible_additional_names = filter_hidden_fields(
            self.request.user, self.model, additional_field_names
        )
        export_additional_fields = [
            f for f in export_additional_fields if f["name"] in visible_additional_names
        ]
        view_type = self.request.GET.get("view_type") or self.get_default_view_type()
        context["saved_list_name"] = None  # default

        if view_type and view_type.startswith("saved_list_"):
            try:
                saved_list_id = int(view_type.split("_")[2])
                saved_list = (
                    SavedFilterList.all_objects.filter(id=saved_list_id)
                    .filter(Q(user=self.request.user) | Q(is_public=True))
                    .first()
                )
                if saved_list:
                    context["saved_list_name"] = saved_list.name
                    context["saved_list_is_owner"] = (
                        saved_list.user_id == self.request.user.id
                    )
            except (IndexError, ValueError):
                pass
        context["view_type"] = view_type
        context["filter_fields"] = filter_fields
        context["export_additional_fields"] = export_additional_fields
        context["filter_push_url"] = "true" if self.filter_url_push else "false"
        context["model_verbose_name"] = self.model._meta.verbose_name_plural
        context["model_name"] = self.model.__name__
        context["no_record_add_button"] = self.no_record_add_button or {}
        context["no_record_section"] = self.no_record_section
        context["no_record_msg"] = self.no_record_msg
        context["no_found_img"] = self.no_found_img
        context["bulk_update_two_column"] = self.bulk_update_two_column
        header_attrs_dict = {}
        for item in self.header_attrs:
            for col_name, attrs in item.items():
                header_attrs_dict[col_name] = attrs

        col_attrs_dict = {}
        visible_columns = self._get_columns()

        if not visible_columns and self.columns:
            # Filter hidden fields even in fallback case
            field_names = [
                col[1] if isinstance(col, (tuple, list)) and len(col) >= 2 else col
                for col in self.columns
            ]
            visible_field_names = filter_hidden_fields(
                self.request.user, self.model, field_names
            )
            visible_columns = [
                [col[0], col[1]]
                for col in self.columns
                if (col[1] if isinstance(col, (tuple, list)) and len(col) >= 2 else col)
                in visible_field_names
            ]

        if self.col_attrs and visible_columns:
            first_column_field = visible_columns[0][1]
            for item in self.col_attrs:
                for col_name, attrs in item.items():
                    col_attrs_dict[first_column_field] = attrs
                    break
                break

        context["header_attrs"] = header_attrs_dict
        context["col_attrs"] = col_attrs_dict

        field_operators = {}
        field_types = {}
        choices = {}

        operator_display = {
            "exact": "Equals",
            "iexact": "Equals (case insensitive)",
            "icontains": "Contains",
            "ne": "Not Equals",
            "gt": "Greater than",
            "lt": "Less than",
            "gte": "Greater than or equal to",
            "lte": "Less than or equal to",
            "startswith": "Starts with",
            "istartswith": "Starts with",
            "endswith": "Ends with",
            "iendswith": "Ends with",
            "date_range": "Between",
            "between": "Between",
            "isnull": "Is empty",
            "isnotnull": "Is not empty",
        }
        context["operator_display"] = operator_display
        context["pinned_view"] = PinnedView.all_objects.filter(
            user=self.request.user, model_name=self.model.__name__
        ).first()
        field_verbose_names = {}
        for field in filter_fields:
            field_operators[field["name"]] = field.get("operators", [])
            field_types[field["name"]] = field.get("type", [])
            choices[field["name"]] = field.get("choices", [])
            field_verbose_names[field["name"]] = field.get("verbose_name", "")

        context["field_verbose_names"] = field_verbose_names
        context["columns"] = self._get_columns()
        context["raw_attrs"] = self.raw_attrs
        context["view_id"] = self.view_id
        context["action_method"] = self.action_method
        context["bulk_export_option"] = self.bulk_export_option
        context["current_sort"] = self.request.GET.get("sort", self.default_sort_field)
        context["exclude_columns_from_sorting"] = self.exclude_columns_from_sorting
        context["current_direction"] = self.request.GET.get(
            "direction", self.default_sort_direction
        )
        context["current_query"] = self.request.GET.urlencode()
        context["is_htmx_request"] = self.request.headers.get("HX-Request") == "true"
        context["has_next"] = False
        context["next_page"] = None
        if "page_obj" in context and context["page_obj"] is not None:
            context["has_next"] = context["page_obj"].has_next()
            if context["has_next"]:
                context["next_page"] = context["page_obj"].next_page_number()
        context["search_url"] = self.search_url or self.request.path
        context["main_url"] = self.main_url or self.request.path
        query_params = {
            item: self.request.GET.getlist(item) for item in self.request.GET
        }
        context["query_params"] = query_params

        filter_rows = []
        if (
            query_params.get("field")
            and self.request.GET.get("add_filter_row") != "true"
        ):
            for i, field in enumerate(query_params["field"]):
                field_info = next((f for f in filter_fields if f["name"] == field), {})
                raw_value = (
                    query_params.get("value", [None])[i]
                    if i < len(query_params.get("value", []))
                    else None
                )

                # Convert ForeignKey ID to display value
                display_value = raw_value
                if field_info.get("type") == "foreignkey" and raw_value:
                    try:
                        # Get the related model field
                        model_field = self.model._meta.get_field(field)
                        related_model = model_field.related_model

                        # Fetch the related object and get its string representation
                        related_obj = related_model.objects.get(pk=raw_value)
                        display_value = str(related_obj)
                    except Exception:
                        # If anything fails, keep the raw value
                        display_value = raw_value
                elif field_info.get("type") == "choice" and raw_value:
                    try:
                        # Get the field and its choices
                        field_obj = self.model._meta.get_field(field)
                        if field_obj.choices:
                            choices_dict = dict(field_obj.choices)
                            display_value = choices_dict.get(raw_value, raw_value)
                        else:
                            display_value = raw_value
                    except Exception:
                        display_value = raw_value

                start_value = (
                    query_params.get("start_value", [None])[i]
                    if i < len(query_params.get("start_value", []))
                    else None
                )
                end_value = (
                    query_params.get("end_value", [None])[i]
                    if i < len(query_params.get("end_value", []))
                    else None
                )
                field_type = field_info.get("type")

                def _parse_filter_value(val, ftype):
                    if not val or ftype not in ("date", "datetime", "time"):
                        return None
                    if ftype == "datetime":
                        return parse_datetime(val)
                    if ftype == "date":
                        return parse_date(val)
                    if ftype == "time":
                        return parse_time(val)
                    return None

                value_obj = _parse_filter_value(raw_value, field_type)
                start_value_obj = _parse_filter_value(start_value, field_type)
                end_value_obj = _parse_filter_value(end_value, field_type)

                row = {
                    "row_id": i,
                    "field": field,
                    "operator": (
                        query_params.get("operator", [None])[i]
                        if i < len(query_params.get("operator", []))
                        else None
                    ),
                    "value": raw_value,
                    "raw_value": display_value,
                    "start_value": start_value,
                    "end_value": end_value,
                    "value_obj": value_obj,
                    "start_value_obj": start_value_obj,
                    "end_value_obj": end_value_obj,
                    "operators": field_operators.get(field, []),
                    "type": field_types.get(field, []),
                    "choices": choices.get(field, []),
                    "model": field_info.get("model", None),  # Use field_info
                    "app_label": field_info.get("app_label", None),
                    "verbose_name": field_verbose_names.get(field, field),
                    "operator_display": operator_display.get(
                        (
                            query_params.get("operator", [None])[i]
                            if i < len(query_params.get("operator", []))
                            else None
                        ),
                        (
                            query_params.get("operator", [None])[i]
                            if i < len(query_params.get("operator", []))
                            else None
                        ),
                    ),
                }
                filter_rows.append(row)
        else:
            filter_rows = [
                {
                    "row_id": 0,
                    "field": None,
                    "operator": None,
                    "value": None,
                    "operators": [],
                }
            ]

        context["filter_rows"] = filter_rows
        context["last_row_id"] = len(filter_rows) - 1

        # Add filter_class_path and parent_model_path for Select2 pagination
        if self.filterset_class:
            context["filter_class_path"] = (
                f"{self.filterset_class.__module__}.{self.filterset_class.__name__}"
            )
            context["parent_model_path"] = (
                f"{self.model._meta.app_label}.{self.model._meta.model_name}"
            )
        else:
            context["filter_class_path"] = None
            context["parent_model_path"] = None

        if hasattr(self, "filterset"):
            context["filterset"] = self.filterset

        if self.actions and len(self.actions) > self.max_visible_actions:
            context["visible_actions"] = self.actions[: self.max_visible_actions]
            context["dropdown_actions"] = self.actions[self.max_visible_actions :]
            context["use_dropdown"] = True
        else:
            context["visible_actions"] = self.actions
            context["dropdown_actions"] = []
            context["use_dropdown"] = False

        context["model_name"] = self.model.__name__
        context["app_label"] = self.model._meta.app_label
        context["total_records_count"] = self.get_queryset().count()
        context["selected_ids"] = list(self.get_queryset().values_list("id", flat=True))
        context["selected_ids_json"] = json.dumps(context["selected_ids"])
        context["custom_bulk_actions"] = self.custom_bulk_actions
        context["additional_action_button"] = self.additional_action_button
        # Only show fields in bulk update form when user has read+write permission
        editable_bulk_field_names = get_editable_fields(
            self.request.user, self.model, self.bulk_update_fields
        )
        bulk_update_fields_metadata = [
            field
            for field in filter_fields
            if field["name"] in editable_bulk_field_names
        ]
        context["bulk_update_fields"] = bulk_update_fields_metadata
        context["bulk_select_option"] = self.bulk_select_option
        context["bulk_update_option"] = self.bulk_update_option
        context["enable_sorting"] = self.enable_sorting
        context["sorting_target"] = self.sorting_target
        context["bulk_delete_enabled"] = self.bulk_delete_enabled
        queryset_ids = list(self.get_queryset().values_list("id", flat=True))
        session_key = f"list_view_queryset_ids_{self.model._meta.model_name}"
        self.request.session[session_key] = queryset_ids
        query_params = self.request.GET.copy()
        if "page" in query_params:
            del query_params["page"]
        context["search_params"] = query_params.urlencode()
        # context["bulk_delete_url"] = reverse("horilla_generics:generic_bulk_delete")
        context["filter_set_class"] = self.filterset_class
        context["table_width"] = self.table_width
        context["table_class"] = self.table_class
        context["table_height_as_class"] = self.table_height_as_class
        context["save_to_list_option"] = self.save_to_list_option

        # Let helper inject quick filter-related context
        quick_filter.update_quick_filter_context(context, self)
        return context
