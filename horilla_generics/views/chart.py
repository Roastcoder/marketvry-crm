"""
Chart layout view (Zoho-style): same filters as list; group by any FK/choice/boolean
field; chart types aligned with reports/dashboards (horilla_charts.js).
"""

# Standard library
import json
import logging
from collections import defaultdict
from urllib.parse import urlencode

# Django
from django.db.models import BooleanField, Count, ForeignKey
from django.utils.text import slugify

# First-party
from horilla.db import models as horilla_models
from horilla.urls import reverse
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _
from horilla_core.models import HorillaContentType, KanbanGroupBy
from horilla_core.utils import get_user_field_permission
from horilla_generics.views.list import HorillaListView
from horilla_utils.methods import get_section_info_for_model

logger = logging.getLogger(__name__)

CHART_TYPE_CHOICES = [
    ("column", _("Column Chart")),
    ("line", _("Line Chart")),
    ("pie", _("Pie Chart")),
    ("funnel", _("Funnel")),
    ("bar", _("Bar Chart")),
    ("donut", _("Donut")),
    ("stacked_vertical", _("Stacked Vertical")),
    ("stacked_horizontal", _("Stacked Horizontal")),
    ("scatter", _("Scatter")),
    ("treemap", _("Treemap")),
    ("area", _("Area Chart")),
    ("heatmap", _("Heatmap")),
    ("sankey", _("Sankey")),
    ("radar", _("Radar Chart")),
]
CHART_TYPE_VALUES = tuple(c[0] for c in CHART_TYPE_CHOICES)


@method_decorator(htmx_required, name="dispatch")
class HorillaChartView(HorillaListView):
    """
    Chart view: aggregates the filtered queryset by a dimension field (FK, choice,
    or boolean). Chart type selectable; stacked/scatter fall back to column/bar
    when only one dimension (same as EChartsConfig).
    """

    template_name = "chart_view.html"
    bulk_select_option = False
    table_class = False
    paginate_by = None
    default_chart_type = "column"
    allowed_chart_types = CHART_TYPE_VALUES
    chart_group_by_param = "chart_group_by"
    chart_stack_by_param = "chart_stack_by"
    # Sentinel for "Single dimension" in radar Stack by dropdown (Select2 doesn't handle value="" well)
    chart_stack_by_single = "__single__"
    STACKED_CHART_TYPES = (
        "stacked_vertical",
        "stacked_horizontal",
        "heatmap",
        "sankey",
        "radar",
    )

    def _get_kanban_exclude_include_fields(self, view_type="group_by"):
        exclude_str = getattr(self, "exclude_kanban_fields", "") or ""
        exclude_fields = [f.strip() for f in exclude_str.split(",") if f.strip()]
        include_fields = getattr(self, "include_kanban_fields", None)
        return exclude_fields, include_fields

    def _field_is_chart_dimension(self, field):
        """True if we can aggregate queryset.values(field)."""
        if getattr(field, "editable", True) is False:
            return False
        if isinstance(field, ForeignKey):
            return True
        if isinstance(field, BooleanField):
            return True
        if isinstance(field, horilla_models.CharField) and field.choices:
            return True
        # IntegerField etc. with choices
        if getattr(field, "choices", None):
            return True
        return False

    def get_chart_dimension_choices(self):
        """
        (field_name, verbose_name) for every FK, choice, and boolean field
        the user may use as chart dimension. Respects exclude_kanban_fields,
        include_kanban_fields, and hidden field permissions.
        """
        exclude_fields, include_fields = self._get_kanban_exclude_include_fields()
        exclude_fields = list(exclude_fields) + ["country"]
        choices = []
        for field in self.model._meta.get_fields():
            if not getattr(field, "name", None):
                continue
            if getattr(field, "many_to_many", False):
                continue
            if not getattr(field, "concrete", True):
                continue
            if getattr(field, "editable", True) is False:
                continue
            if field.name in exclude_fields:
                continue
            if include_fields is not None and field.name not in include_fields:
                continue
            if not self._field_is_chart_dimension(field):
                continue
            choices.append(
                (field.name, str(getattr(field, "verbose_name", None) or field.name))
            )
        if self.request.user and choices:
            from horilla_core.utils import filter_hidden_fields

            field_names = [c[0] for c in choices]
            allowed = filter_hidden_fields(self.request.user, self.model, field_names)
            choices = [c for c in choices if c[0] in allowed]
        return choices

    def _get_allowed_group_by_fields(self, view_type="group_by"):
        """Legacy kanban/group-by field names only (subset of chart dimensions)."""
        model_name = self.model.__name__
        app_label = self.model._meta.app_label
        exclude_fields, include_fields = self._get_kanban_exclude_include_fields(
            view_type
        )
        temp = KanbanGroupBy(model_name=model_name, app_label=app_label)
        choices = temp.get_model_groupby_fields(
            user=self.request.user,
            exclude_fields=exclude_fields,
            include_fields=include_fields,
        )
        return [c[0] for c in choices]

    def _is_field_visible_for_group_by(self, field_name):
        if not field_name:
            return False
        perm = get_user_field_permission(self.request.user, self.model, field_name)
        return perm != "hidden"

    def get_group_by_field(self):
        """
        Effective dimension field:
        1) chart_group_by GET if valid and visible
        2) else KanbanGroupBy group_by preference if in chart dimensions
        3) else first allowed chart dimension
        """
        choices = self.get_chart_dimension_choices()
        allowed_names = {c[0] for c in choices}

        requested = self.request.GET.get(self.chart_group_by_param)
        if requested and requested in allowed_names:
            if self._is_field_visible_for_group_by(requested):
                return requested

        model_name = self.model.__name__
        app_label = self.model._meta.app_label
        default_group = KanbanGroupBy.all_objects.filter(
            model_name=model_name,
            app_label=app_label,
            user=self.request.user,
            view_type="group_by",
        ).first()
        preferred = (
            default_group.field_name
            if default_group
            else getattr(self, "group_by_field", None)
        )
        if (
            preferred
            and preferred in allowed_names
            and self._is_field_visible_for_group_by(preferred)
        ):
            return preferred

        legacy_allowed = self._get_allowed_group_by_fields(view_type="group_by")
        for field_name in legacy_allowed:
            if field_name in allowed_names and self._is_field_visible_for_group_by(
                field_name
            ):
                return field_name

        for field_name, __ in choices:
            if self._is_field_visible_for_group_by(field_name):
                return field_name
        return None

    def _label_for_group_key(self, field, group_key):
        """Human-readable label for aggregate bucket."""
        if group_key is None:
            return str(_("(empty)"))
        if isinstance(field, BooleanField):
            if group_key is True:
                return str(_("Yes"))
            if group_key is False:
                return str(_("No"))
            return str(_("(empty)"))
        if hasattr(field, "choices") and field.choices:
            for value, label in field.choices:
                if value == group_key:
                    return str(label)
            return str(group_key)
        if isinstance(field, ForeignKey):
            try:
                related = field.related_model.objects.get(pk=group_key)
                return str(related)
            except Exception:
                return str(group_key)
        return str(group_key)

    def _list_drill_url(self, filter_field, filter_value):
        """
        URL for chart segment click. Same as report/dashboard: apply_filter + field +
        operator + value so HorillaFilterSet filter_queryset applies. main_url +
        layout=list so HTMX hx-select #mainContent works.
        """
        main_url = getattr(self, "main_url", None)
        if main_url:
            base = str(main_url).split("?")[0].rstrip("/") + "/"
        else:
            list_url = getattr(self, "search_url", None) or ""
            base = str(list_url).split("?")[0] if list_url else ""
        if not base:
            return "#"

        # Value string for filter (boolean/choice/FK pk) — matches report_detail _generate_stacked_chart_data
        if filter_value is True:
            value_str = "true"
        elif filter_value is False:
            value_str = "false"
        elif filter_value is None:
            value_str = ""
        else:
            value_str = str(filter_value)

        params = {
            "layout": "list",
            "apply_filter": "true",
            "field": filter_field,
            "operator": "exact",
            "value": value_str,
        }
        section_info = get_section_info_for_model(self.model)
        if section_info.get("section"):
            params["section"] = section_info["section"]
        # Preserve search / view_type if present (no chart UI keys)
        for key in ("search", "view_type"):
            v = self.request.GET.get(key)
            if v is not None and v != "":
                params[key] = v
        qs = urlencode(params, doseq=True)
        return f"{base}?{qs}"

    def _filter_value_str(self, filter_value):
        """String for apply_filter value param (boolean/choice/FK pk)."""
        if filter_value is True:
            return "true"
        if filter_value is False:
            return "false"
        if filter_value is None:
            return ""
        return str(filter_value)

    def _list_drill_url_two(self, field1, value1, field2, value2):
        """
        URL applying BOTH filters (first group + second group). HorillaFilterSet
        filter_queryset uses getlist('field') / getlist('value') — multiple triplets AND.
        """
        main_url = getattr(self, "main_url", None)
        if main_url:
            base = str(main_url).split("?")[0].rstrip("/") + "/"
        else:
            list_url = getattr(self, "search_url", None) or ""
            base = str(list_url).split("?")[0] if list_url else ""
        if not base:
            return "#"

        v1 = self._filter_value_str(value1)
        v2 = self._filter_value_str(value2)
        pairs = [
            ("layout", "list"),
            ("apply_filter", "true"),
            ("field", field1),
            ("operator", "exact"),
            ("value", v1),
            ("field", field2),
            ("operator", "exact"),
            ("value", v2),
        ]
        section_info = get_section_info_for_model(self.model)
        if section_info.get("section"):
            pairs.insert(2, ("section", section_info["section"]))
        for key in ("search", "view_type"):
            v = self.request.GET.get(key)
            if v is not None and v != "":
                pairs.append((key, v))
        qs = urlencode(pairs)
        return f"{base}?{qs}"

    def _chart_field_supports_aggregation(self, field):
        """Whether values(field).annotate(Count) is valid."""
        if isinstance(field, (ForeignKey, BooleanField)):
            return True
        if hasattr(field, "choices") and field.choices:
            return True
        if getattr(field, "choices", None):
            return True
        return False

    def build_chart_payload(self, queryset, group_by):
        """Return {labels, data, urls} for EChartsConfig."""
        field = self.model._meta.get_field(group_by)
        if not self._chart_field_supports_aggregation(field):
            return None, _("This field cannot be used as chart dimension.")

        rows = list(
            queryset.values(group_by).annotate(_count=Count("pk")).order_by("-_count")
        )
        labels = []
        data = []
        urls = []
        list_url = getattr(self, "search_url", None) or ""
        if hasattr(list_url, "__str__"):
            list_url = str(list_url)

        for row in rows:
            key = row[group_by]
            count = row["_count"]
            label = self._label_for_group_key(field, key)
            labels.append(label)
            data.append(count)
            if list_url:
                val = (
                    ""
                    if key is None
                    else ("true" if key is True else "false" if key is False else key)
                )
                urls.append(self._list_drill_url(group_by, val))
            else:
                urls.append("#")

        return {"labels": labels, "data": data, "urls": urls}, None

    def get_stack_by_field(self, primary_field, chart_type=None):
        """
        Second dimension for stacked charts; must differ from primary and be valid.
        For radar chart: returns None when no stack_by is requested (single dimension);
        other stacked types default to first allowed dimension when not requested.
        """
        choices = self.get_chart_dimension_choices()
        allowed = [c[0] for c in choices if c[0] != primary_field]
        if not allowed:
            return None
        requested = self.request.GET.get(self.chart_stack_by_param)
        # Radar: treat empty or sentinel as "Single dimension" (no second axis)
        if chart_type == "radar" and (
            requested is None
            or requested == ""
            or requested == self.chart_stack_by_single
        ):
            return None
        if requested in allowed and self._is_field_visible_for_group_by(requested):
            return requested
        # Other stacked types: default to first allowed when not requested
        if chart_type == "radar":
            return None
        return allowed[0]

    def build_stacked_payload(self, queryset, primary, secondary):
        """
        Build stackedData for EChartsConfig: categories (X) + series (stack segments).
        Each series has name + data array aligned with categories.
        """
        field_p = self.model._meta.get_field(primary)
        field_s = self.model._meta.get_field(secondary)
        if not self._chart_field_supports_aggregation(
            field_p
        ) or not self._chart_field_supports_aggregation(field_s):
            return None, _("Both fields must support chart grouping.")

        rows = list(
            queryset.values(primary, secondary).annotate(_count=Count("pk")).order_by()
        )
        # pivot[pkey][skey] = count
        pivot = defaultdict(lambda: defaultdict(int))
        primary_keys = []
        secondary_keys_order = []
        seen_p = set()
        seen_s = set()
        for row in rows:
            pk, sk = row[primary], row[secondary]
            pivot[pk][sk] += row["_count"]
            if pk not in seen_p:
                seen_p.add(pk)
                primary_keys.append(pk)
            if sk not in seen_s:
                seen_s.add(sk)
                secondary_keys_order.append(sk)

        if not primary_keys or not secondary_keys_order:
            return None, _("Not enough data for stacked chart.")

        categories = [self._label_for_group_key(field_p, k) for k in primary_keys]
        secondary_keys = secondary_keys_order

        list_url = str(getattr(self, "search_url", "") or "")
        series = []
        for sk in secondary_keys:
            name = self._label_for_group_key(field_s, sk)
            row_data = []
            for pk in primary_keys:
                v = int(pivot[pk].get(sk, 0))
                if list_url and v > 0:
                    row_data.append(
                        {
                            "value": v,
                            "url": self._list_drill_url_two(primary, pk, secondary, sk),
                        }
                    )
                else:
                    row_data.append(v)
            series.append({"name": name, "data": row_data})

        stacked_data = {"categories": categories, "series": series}
        totals = [sum(pivot[pk].values()) if pivot[pk] else 0 for pk in primary_keys]
        urls = []
        if list_url:
            for pk in primary_keys:
                val = (
                    ""
                    if pk is None
                    else ("true" if pk is True else "false" if pk is False else pk)
                )
                urls.append(self._list_drill_url(primary, val))
        else:
            urls = ["#"] * len(categories)

        return {
            "stackedData": stacked_data,
            "labels": categories,
            "data": totals,
            "urls": urls,
        }, None

    def get_context_data(self, **kwargs):
        if not hasattr(self, "object_list"):
            self.object_list = self.get_queryset()
        context = super().get_context_data(**kwargs)
        queryset = self.object_list

        dimension_choices = self.get_chart_dimension_choices()
        context["chart_dimension_choices"] = dimension_choices
        context["chart_group_by_param"] = self.chart_group_by_param
        context["chart_stack_by_param"] = self.chart_stack_by_param
        context["chart_stack_by_single"] = self.chart_stack_by_single
        context["stack_dimension_choices"] = []
        context["stack_by_field"] = None
        context["chart_push_url_json"] = "null"

        group_by = self.get_group_by_field()
        context["group_by_field"] = group_by

        if not group_by:
            context["chart_add_to_dashboard_url"] = None
            context["chart_show_add_to_dashboard"] = False
            context["chart_error"] = _(
                "No suitable field for chart grouping (need a choice, foreign key, or boolean field)."
            )
            context["chart_config_json"] = "{}"
            context["chart_type_choices"] = CHART_TYPE_CHOICES
            context["chart_htmx_url"] = self.request.get_full_path()
            context["chart_push_url"] = None
            context["chart_push_url_json"] = "null"
            return context

        try:
            payload, err = self.build_chart_payload(queryset, group_by)
        except Exception as e:
            logger.exception("Chart payload build failed")
            context["chart_error"] = str(e)
            context["chart_config_json"] = "{}"
            context["chart_type_choices"] = CHART_TYPE_CHOICES
            context["chart_htmx_url"] = self.request.get_full_path()
            context["chart_push_url"] = None
            context["chart_push_url_json"] = "null"
            return context

        if err:
            context["chart_error"] = err
            context["chart_config_json"] = "{}"
            context["chart_type_choices"] = CHART_TYPE_CHOICES
            context["chart_htmx_url"] = self.request.get_full_path()
            context["chart_push_url"] = None
            context["chart_push_url_json"] = "null"
            return context

        chart_type = (
            self.request.GET.get("chart_type") or self.default_chart_type
        ).lower()
        if chart_type not in self.allowed_chart_types:
            chart_type = self.default_chart_type

        field = self.model._meta.get_field(group_by)
        label_field = str(getattr(field, "verbose_name", None) or group_by)

        if chart_type in self.STACKED_CHART_TYPES:
            stack_by = self.get_stack_by_field(group_by, chart_type)
            context["stack_by_field"] = stack_by
            context["chart_stack_by_param"] = self.chart_stack_by_param
            context["stack_dimension_choices"] = [
                c for c in dimension_choices if c[0] != group_by
            ]
            if stack_by:
                stacked_payload, stacked_err = self.build_stacked_payload(
                    queryset, group_by, stack_by
                )
            else:
                stacked_payload, stacked_err = None, None
            if stacked_err or not stacked_payload:
                # Fall back to simple column/bar if stacked build fails
                config = {
                    "type": chart_type,
                    "labels": payload["labels"],
                    "data": payload["data"],
                    "labelField": label_field,
                    "urls": payload.get("urls") or [],
                }
            else:
                field_s = self.model._meta.get_field(stack_by)
                label_s = str(getattr(field_s, "verbose_name", None) or stack_by)
                config = {
                    "type": chart_type,
                    "labels": stacked_payload["labels"],
                    "data": stacked_payload["data"],
                    "labelField": f"{label_field} / {label_s}",
                    "urls": stacked_payload.get("urls") or [],
                    "stackedData": stacked_payload["stackedData"],
                    "hasMultipleGroups": True,
                }
        else:
            context["stack_by_field"] = None
            context["stack_dimension_choices"] = []
            config = {
                "type": chart_type,
                "labels": payload["labels"],
                "data": payload["data"],
                "labelField": label_field,
                "urls": payload.get("urls") or [],
            }
        context["chart_config_json"] = json.dumps(config)
        context["chart_type"] = chart_type
        context["chart_type_choices"] = CHART_TYPE_CHOICES
        context["chart_error"] = None
        context["chart_dom_id"] = f"chart-view-{slugify(self.view_id or 'generic')}"

        model_label = str(
            getattr(self.model._meta, "verbose_name_plural", None)
            or self.model._meta.verbose_name
            or self.model._meta.model_name
        )
        export_slug = slugify(f"{model_label}-by-{label_field}")
        if not export_slug:
            export_slug = (
                slugify(f"{self.model._meta.model_name}-by-{group_by}") or "chart"
            )
        context["chart_export_filename"] = export_slug

        context["chart_add_to_dashboard_url"] = None
        context["chart_show_add_to_dashboard"] = False
        if payload.get("labels"):
            user = getattr(self.request, "user", None)
            if user and (
                getattr(user, "is_superuser", False)
                or user.has_perm("horilla_dashboard.change_dashboard")
                or user.has_perm("horilla_dashboard.add_dashboard")
            ):
                try:
                    ct = HorillaContentType.objects.get_for_model(self.model)
                    q = {
                        "module_id": ct.pk,
                        "grouping_field": group_by,
                        "chart_type": chart_type,
                    }
                    if context.get("stack_by_field"):
                        q[self.chart_stack_by_param] = context["stack_by_field"]
                    context["chart_add_to_dashboard_url"] = (
                        reverse("horilla_dashboard:chart_view_to_dashboard")
                        + "?"
                        + urlencode(q)
                    )
                    context["chart_show_add_to_dashboard"] = True
                except Exception:
                    logger.exception("chart_add_to_dashboard_url build failed")

        params = self.request.GET.copy()
        params.pop(self.chart_group_by_param, None)
        params.pop("chart_type", None)
        params.pop(self.chart_stack_by_param, None)
        chart_path = self.request.path
        if params:
            context["chart_htmx_url"] = f"{chart_path}?{urlencode(params, doseq=True)}"
        else:
            context["chart_htmx_url"] = chart_path

        main_url = getattr(self, "main_url", None)
        if main_url:
            main_path = str(main_url).split("?")[0].rstrip("/") + "/"
            push_params = self.request.GET.copy()
            push_params["layout"] = "chart"
            push_params[self.chart_group_by_param] = group_by
            push_params["chart_type"] = chart_type
            if context.get("stack_by_field"):
                push_params[self.chart_stack_by_param] = context["stack_by_field"]
            context["chart_push_url"] = (
                f"{main_path}?{urlencode(push_params, doseq=True)}"
            )
            context["chart_push_url_json"] = json.dumps(context["chart_push_url"])
        else:
            context["chart_push_url"] = None
            context["chart_push_url_json"] = "null"

        return context

    def render_to_response(self, context, **response_kwargs):
        """Push canonical main_url (layout=chart) so the bar stays off the chart endpoint."""
        response = super().render_to_response(context, **response_kwargs)
        push_url = context.get("chart_push_url")
        if push_url and self.request.headers.get("HX-Request"):
            response["HX-Push-Url"] = push_url
        return response
