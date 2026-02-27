"""Views for managing horilla_dashboard and their components."""

# Standard library imports
import json
import logging
import re
from urllib.parse import urlencode, urlparse

# Third-party imports (Django)
from django.apps import apps
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, Count, ForeignKey, Q, When
from django.http import HttpResponse, JsonResponse, QueryDict
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView, View

from horilla.decorator import (
    htmx_required,
    permission_required,
    permission_required_or_denied,
)
from horilla.exceptions import HorillaHttp404

# First-party / Horilla imports
from horilla.http import HorillaRefreshResponse
from horilla.utils.choices import DISPLAYABLE_FIELD_TYPES
from horilla.utils.shortcuts import get_object_or_404
from horilla_core.models import HorillaContentType
from horilla_dashboard.filters import DashboardFilter
from horilla_dashboard.forms import DashboardCreateForm, DashboardForm
from horilla_dashboard.models import (
    ComponentCriteria,
    Dashboard,
    DashboardComponent,
    DashboardFolder,
    DefaultHomeLayoutOrder,
)
from horilla_generics.mixins import RecentlyViewedMixin
from horilla_generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)
from horilla_reports.models import Report
from horilla_utils.methods import get_section_info_for_model
from horilla_utils.middlewares import _thread_local

# Local imports
from .utils import (
    DATE_RANGE_CHOICES,
    DefaultDashboardGenerator,
    apply_date_range_to_queryset,
    validate_custom_date_params,
    validate_date_range_request,
)

logger = logging.getLogger(__name__)


class HomePageView(LoginRequiredMixin, TemplateView):
    """View to render the home page, showing default or dynamic dashboard."""

    template_name = "home/default_home.html"

    def get(self, request, *args, **kwargs):
        """Validate date range, then render default or dynamic dashboard as home."""
        redirect_url = validate_date_range_request(request)
        if redirect_url:
            return redirect(redirect_url)

        try:
            default_dashboard = Dashboard.get_default_dashboard(request.user)

            if default_dashboard:
                return self.render_dashboard_as_home(request, default_dashboard)
        except ImportError:
            logger.warning("Dashboard model not found")

        return self.render_dynamic_default_dashboard(request)

    def render_dashboard_as_home(self, request, dashboard):
        """Render the specified dashboard as the home page."""
        try:

            detail_view = DashboardDetailView()
            detail_view.request = request
            detail_view.object = dashboard
            detail_view.kwargs = {"pk": dashboard.pk}

            mutable_get = request.GET.copy()
            mutable_get["section"] = "home"
            mutable_get["is_home"] = "true"
            if "date_range" in request.GET:
                mutable_get["date_range"] = request.GET["date_range"]
            if "date_from" in request.GET:
                mutable_get["date_from"] = request.GET["date_from"]
            if "date_to" in request.GET:
                mutable_get["date_to"] = request.GET["date_to"]
            request.GET = mutable_get

            context = detail_view.get_context_data(object=dashboard)
            template_name = detail_view.get_template_names()[0]

            return self.render_to_response(context, template_name=template_name)
        except ImportError:
            return self.render_dynamic_default_dashboard(request)

    def render_dynamic_default_dashboard(self, _request):
        """Render a dynamic default dashboard on the home page."""
        context = self.get_dynamic_default_context()
        return self.render_to_response(context, template_name="home/default_home.html")

    def get_dynamic_default_context(self):
        """Generate context data for a dynamic default dashboard."""
        context = super().get_context_data()

        user_company = getattr(self.request.user, "company", None)
        date_range = self.request.GET.get("date_range")
        if date_range == "all":
            date_range = None
        date_from = self.request.GET.get("date_from")
        date_to = self.request.GET.get("date_to")
        date_range, date_from, date_to = validate_custom_date_params(
            date_range, date_from, date_to
        )
        if date_range is None:
            date_from = None
            date_to = None

        generator = DefaultDashboardGenerator(
            self.request.user,
            user_company,
            date_range=date_range,
            date_from=date_from,
            date_to=date_to,
        )

        kpi_data = generator.generate_kpi_data()
        kpi_data.sort(key=lambda k: k.get("title", ""))
        for id, data in enumerate(kpi_data):
            data["order"] = id

        chart_data = generator.generate_chart_data()
        table_data = generator.generate_table_data()

        user_dashboards = []
        try:
            user_dashboards = Dashboard.objects.filter(
                dashboard_owner=self.request.user, is_active=True
            ).order_by("-created_at")[:5]
        except ImportError:
            pass

        base_url = self.request.build_absolute_uri(self.request.path).split("?")[0]
        query_params = self.request.GET.copy()
        query_params.pop("date_range", None)
        query_params.pop("date_from", None)
        query_params.pop("date_to", None)
        base_query = query_params.urlencode()
        date_range_base_url = f"{base_url}?{base_query}" if base_query else base_url

        default_home_order = {}
        user_has_custom_default_home_layout = False
        try:
            layout_order = DefaultHomeLayoutOrder.objects.filter(
                user=self.request.user, dashboard__isnull=True
            ).first()
            if layout_order and isinstance(layout_order.order, dict):
                default_home_order = layout_order.order
                user_has_custom_default_home_layout = True
        except Exception:
            pass

        default_home_blocks = []
        chart_list = list(enumerate(chart_data)) if chart_data else []
        table_list = list(enumerate(table_data)) if table_data else []
        ci, ti = 0, 0
        while ci < len(chart_list) or ti < len(table_list):
            for _unused in range(2):
                if ci < len(chart_list):
                    idx, ch = chart_list[ci]
                    default_home_blocks.append(
                        {
                            "type": "chart",
                            "chart_index": idx,
                            "data": ch,
                        }
                    )
                    ci += 1
            if ti < len(table_list):
                idx, tb = table_list[ti]
                default_home_blocks.append(
                    {
                        "type": "table",
                        "table_index": idx,
                        "data": tb,
                    }
                )
                ti += 1

        if default_home_order:
            kpi_order = default_home_order.get("kpi", [])
            charts_tables_order = default_home_order.get("chartsAndTables", [])

            try:
                if kpi_order and kpi_data:
                    kpi_dict = {f"default-kpi-{kpi['order']}": kpi for kpi in kpi_data}
                    kpi_data = [kpi_dict[key] for key in kpi_order if key in kpi_dict]

                # Reorder charts and tables
                if charts_tables_order and default_home_blocks:
                    blocks_dict = {}
                    for block in default_home_blocks:
                        if block["type"] == "chart":
                            key = f"default-chart-{block['chart_index']}"
                        else:
                            key = f"default-table-{block['table_index']}"
                        blocks_dict[key] = block

                    default_home_blocks = [
                        blocks_dict[key]
                        for key in charts_tables_order
                        if key in blocks_dict
                    ]
            except TypeError:
                logger.warning(
                    "Invalid default home layout order for user %s (unhashable type). Resetting.",
                    self.request.user,
                )
                DefaultHomeLayoutOrder.objects.filter(
                    user=self.request.user, dashboard__isnull=True
                ).delete()
                user_has_custom_default_home_layout = False
                messages.error(
                    self.request,
                    _(
                        "Your saved layout order was invalid and has been reset. "
                        "Please reorder the dashboard again if needed."
                    ),
                )
                default_home_order = {}

        context.update(
            {
                "is_default_home": True,
                "is_dynamic_dashboard": True,
                "kpi_data": kpi_data,
                "chart_data": chart_data,
                "table_data": table_data,
                "default_home_blocks": default_home_blocks,
                "user_dashboards": user_dashboards,
                "has_dashboards": bool(user_dashboards),
                "show_create_dashboard_prompt": True,
                "available_models_count": len(generator.models),
                "date_range": date_range,
                "date_range_choices": DATE_RANGE_CHOICES,
                "date_range_base_url": date_range_base_url,
                "date_from": date_from,
                "date_to": date_to,
                "default_home_layout_order": default_home_order,
                "user_has_custom_default_home_layout": user_has_custom_default_home_layout,
            }
        )

        return context

    def render_to_response(self, context, template_name=None, **response_kwargs):
        """Render with optional override of template_name."""
        if template_name:
            self.template_name = template_name
        return super().render_to_response(context, **response_kwargs)


def get_queryset_for_module(user, model):
    """
    Returns queryset for a given model based on user permissions.
    Uses model.OWNER_FIELDS if available.
    """
    app_label = model._meta.app_label
    model_name = model._meta.model_name

    if user.has_perm(f"{app_label}.view_{model_name}"):
        return model.objects.all()

    if user.has_perm(f"{app_label}.view_own_{model_name}"):
        owner_fields = getattr(model, "OWNER_FIELDS", [])
        if not owner_fields:
            return model.objects.none()

        q_filter = Q()
        for field in owner_fields:
            q_filter |= Q(**{field: user})
        return model.objects.filter(q_filter)

    return model.objects.none()


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(
        ["horilla_dashboard.view_dashboard", "horilla_dashboard.view_own_dashboard"]
    ),
    name="dispatch",
)
class DashboardNavbar(LoginRequiredMixin, HorillaNavView):
    """Navigation bar for horilla_dashboard with folder filtering."""

    search_url = reverse_lazy("horilla_dashboard:dashboard_list_view")
    main_url = reverse_lazy("horilla_dashboard:dashboard_list_view")
    filterset_class = DashboardFilter
    one_view_only = True
    filter_option = False
    reload_option = False
    gap_enabled = False
    model_name = "Dashboard"
    model_app_label = "horilla_dashboard"
    search_option = False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        title = self.request.GET.get("title", "Dashboards")
        context["nav_title"] = _(title)
        return context

    @cached_property
    def new_button(self):
        """Button for creating new dashboard"""
        if self.request.user.has_perm(
            "horilla_dashboard.add_dashboard"
        ) or self.request.user.has_perm("horilla_dashboard.add_own_dashboard"):
            return {
                "title": _("New Dashboard"),
                "url": f"""{ reverse_lazy('horilla_dashboard:dashboard_create')}""",
                "attrs": {"id": "dashboard-create"},
            }
        return None

    @cached_property
    def second_button(self):
        """Button for creating dashboard folder"""
        if self.request.user.has_perm(
            "horilla_dashboard.add_dashboardfolder"
        ) or self.request.user.has_perm("horilla_dashboard.add_own_dashboardfolder"):
            return {
                "title": _("New Folder"),
                "url": f"{reverse_lazy('horilla_dashboard:dashboard_folder_create')}?pk={self.request.GET.get('pk', '')}",
                "attrs": {"id": "dashboard-folder-create"},
            }
        return None


@method_decorator(
    permission_required_or_denied(
        ["horilla_dashboard.view_dashboard", "horilla_dashboard.view_own_dashboard"]
    ),
    name="dispatch",
)
class DashboardListView(LoginRequiredMixin, HorillaListView):
    """List view for horilla_dashboard with filtering and actions."""

    model = Dashboard
    template_name = "dashboard_list_view.html"
    view_id = "dashboard-list"
    search_url = reverse_lazy("horilla_dashboard:dashboard_list_view")
    main_url = reverse_lazy("horilla_dashboard:dashboard_list_view")
    table_width = False
    max_visible_actions = 5
    bulk_select_option = False
    sorting_target = f"#tableview-{view_id}"
    # enable_sorting =  False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = _("Dashboards")
        return context

    columns = ["name", "description", "folder", (_("Is Default"), "is_default_col")]

    @cached_property
    def action_method(self):
        """Determine if action column should be shown based on user permissions."""
        action_method = ""
        if (
            self.request.user.has_perm("horilla_dashboard.change_dashboard")
            or self.request.user.has_perm("horilla_dashboard.delete_dashboard")
            or self.request.user.has_perm("horilla_dashboard.view_own_dashboard")
        ):
            action_method = "actions"
        return action_method

    @cached_property
    def col_attrs(self):
        """Define attributes for columns, including action column if applicable."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {}
        if self.request.user.has_perm(
            "horilla_dashboard.view_dashboard"
        ) or self.request.user.has_perm("horilla_dashboard.view_own_dashboard"):
            attrs = {
                "hx-get": f"{{get_detail_view_url}}?{query_string}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select": "#mainContent",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]


@method_decorator(htmx_required, name="dispatch")
class DashboardDefaultToggleView(LoginRequiredMixin, View):
    """Toggle default dashboard for the current user via HTMX"""

    def post(self, request, *args, **kwargs):
        """Handle HTMX POST to toggle the `is_default` flag for a dashboard."""
        try:
            dashboard = Dashboard.objects.get(pk=kwargs["pk"])
            user = request.user
            if (
                user.has_perm("horilla_dashboard.change_dashboard")
                or dashboard.dashboard_owner == user
            ):
                if not dashboard.is_default:
                    Dashboard.objects.filter(
                        dashboard_owner=request.user,
                        company=request.user.company,
                        is_default=True,
                    ).update(is_default=False)
                    dashboard.is_default = True
                    messages.success(request, f"{dashboard.name} set as default.")
                else:
                    dashboard.is_default = False
                    messages.success(request, f"{dashboard.name} removed from default.")
                dashboard.save()
                return HttpResponse("<script>$('#reloadButton').click();</script>")
            return None

        except Exception as e:
            messages.error(request, e)
            return HttpResponse("<script>$('#reloadButton').click();</script>")


@method_decorator(htmx_required, name="dispatch")
class DashboardFavoriteToggleView(LoginRequiredMixin, View):
    """Toggle favorite status of a dashboard for the logged-in user."""

    def post(self, request, *args, **kwargs):
        """Handle POST requests to toggle favorite status of a dashboard folder."""
        try:
            dashboard = Dashboard.objects.get(pk=kwargs["pk"])
        except Exception as e:
            messages.error(request, str(e))
            return HttpResponse("<script>$('#reloadButton').click();</script>")

        user = request.user
        if (
            user.has_perm("horilla_dashboard.change_dashboardfolder")
            or dashboard.dashboard_owner == user
        ):
            if user in dashboard.favourited_by.all():
                dashboard.favourited_by.remove(user)
            else:
                dashboard.favourited_by.add(user)
        return HttpResponse("<script>$('#reloadButton').click();</script>")

    def get(self, request, *args, **kwargs):
        """Handle GET request to return 403 error for non-POST requests."""
        return render(request, "error/403.html")


@method_decorator(
    permission_required_or_denied(
        ["horilla_dashboard.view_dashboard", "horilla_dashboard.view_own_dashboard"]
    ),
    name="dispatch",
)
class DashboardDetailView(RecentlyViewedMixin, LoginRequiredMixin, TemplateView):
    """
    Render the detail view of dashboard page with support for KPIs, charts, and tables.
    """

    model = Dashboard

    def get_template_names(self):
        """
        Return template based on whether this is accessed from home
        """
        section = self.request.GET.get("section")
        is_home = self.request.GET.get("is_home") == "true"
        is_default = (
            self.object.is_default if hasattr(self, "object") and self.object else False
        )

        if section == "home" and is_home and is_default:
            return ["home/home.html"]
        return ["dashboard_detail_view.html"]

    def get_object(self):
        """Retrieve the dashboard object based on the primary key in the URL."""
        if not hasattr(self, "_object"):
            self._object = get_object_or_404(self.model, pk=self.kwargs.get("pk"))
        return self._object

    def get(self, request, *args, **kwargs):
        """Check ownership or view_dashboard permission and date range; then render dashboard."""
        self.object = self.get_object()
        if not self.model.objects.filter(
            dashboard_owner_id=self.request.user, pk=self.kwargs["pk"]
        ).first() and not self.request.user.has_perm(
            "horilla_dashboard.view_dashboard"
        ):
            return render(self.request, "error/403.html")

        redirect_url = validate_date_range_request(request)
        if redirect_url:
            return redirect(redirect_url)

        return super().get(request, *args, **kwargs)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        try:
            self.object = self.get_object()
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                messages.error(self.request, e)
                return HorillaRefreshResponse(request)
            raise HorillaHttp404(e)
        return super().dispatch(request, *args, **kwargs)

    def get_kpi_data(self, component, request):
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
            queryset = get_queryset_for_module(self.request.user, model)
            # conditions = component.conditions.all()

            conditions = component.conditions.all().order_by("sequence")
            queryset = self.apply_conditions(queryset, conditions)

            # KPIs always use count
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

    def get_report_chart_data(self, component, request):
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

            # Include both the field and its ID for foreign keys
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

            # In get_chart_data method, replace the label handling section:

            for item in chart_data:
                label_value = item[group_by_field]

                # Handle display value for choice fields and foreign keys
                try:
                    field = model._meta.get_field(group_by_field)
                    if hasattr(field, "choices") and field.choices:
                        # Handle choice fields - convert key to display value
                        for choice_value, choice_label in field.choices:
                            if choice_value == label_value:
                                label_value = choice_label
                                break
                    elif field.is_relation and label_value is not None:
                        # Handle foreign key fields - get the string representation
                        related_model = field.related_model
                        try:
                            related_obj = related_model.objects.get(pk=label_value)
                            label_value = str(related_obj)
                        except related_model.DoesNotExist:
                            pass
                except Exception:
                    pass

                labels.append(
                    str(label_value) if label_value is not None else "Unknown"
                )
                data.append(float(item["value"]) if item["value"] is not None else 0)

                # For the filter URL, use the original value (key for choices, ID for FK)
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

    def get_chart_data(self, component, request):
        """
        Generate chart data for a dashboard component.
        Returns a dictionary with chart configuration.
        """
        try:
            if component.reports:
                return self.get_report_chart_data(component, request)
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

            # Get filtered queryset
            queryset = get_queryset_for_module(request.user, model)

            # Apply conditions
            conditions = component.conditions.all().order_by("sequence")
            queryset = self.apply_conditions(queryset, conditions)

            if queryset.count() == 0:
                return None

            # Get grouping field - charts always use count aggregation
            group_by_field = component.grouping_field

            if not group_by_field:
                return None

            # Charts always count records
            try:
                field_obj = model._meta.get_field(group_by_field)
                is_fk = field_obj.is_relation
            except Exception:
                is_fk = False

            # Include both the field and its ID for foreign keys
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

            # Get section info for generating filter URLs
            section_info = get_section_info_for_model(model)

            for item in chart_data:
                label_value = item[group_by_field]

                # Handle display value for choice fields
                try:
                    field = model._meta.get_field(group_by_field)
                    if hasattr(field, "choices") and field.choices:
                        for choice_value, choice_label in field.choices:
                            if choice_value == label_value:
                                label_value = choice_label
                                break
                except Exception:
                    pass

                labels.append(
                    str(label_value) if label_value is not None else "Unknown"
                )
                data.append(float(item["value"]) if item["value"] is not None else 0)

                filter_value = item[group_by_field]
                try:
                    field = model._meta.get_field(group_by_field)
                    if field.is_relation:
                        filter_value = item.get(f"{group_by_field}_id", filter_value)
                except Exception:
                    pass

                # Generate filter URL
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
            logger.warning(
                "Failed to generate chart for component %s: %s", component.id, e
            )
            return None

    def apply_conditions(self, queryset, conditions):
        """Apply filter conditions to a queryset with proper type handling."""

        for condition in conditions:
            field = condition.field
            operator = condition.operator
            value = condition.value

            # Skip if value is empty for operators that require a value
            if not value and operator not in ["is_null", "is_not_null"]:
                continue

            try:
                # Get the model field to determine its type
                model = queryset.model
                field_obj = model._meta.get_field(field)

                # Convert value based on field type
                converted_value = value
                if hasattr(field_obj, "get_internal_type"):
                    field_type = field_obj.get_internal_type()

                    # Handle numeric fields
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

                    # Handle boolean fields
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

                    # Handle foreign key fields
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

                # Apply the filter based on operator
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

    def get_table_data(self, component, request):
        """
        Generate table data and context for a dashboard component using HorillaListView.
        """
        model = None
        self.request = request

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

        queryset = get_queryset_for_module(self.request.user, model)
        conditions = component.conditions.all().order_by("sequence")
        queryset = self.apply_conditions(queryset, conditions)

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
        list_view.table_height = False
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
            if first_col_field.startswith("get_") and first_col_field.endswith(
                "_display"
            ):
                first_col_field = first_col_field[4:-8]

        first_obj = page_obj.object_list[0] if page_obj.object_list else None
        col_attrs = {}

        if first_col_field and hasattr(model, "get_detail_url") and first_obj:
            if self.request.user.has_perm(
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

    def post(self, request, *args, **kwargs):
        """Handle POST request for exporting table data from the first table component."""
        dashboard = self.get_object()
        components = DashboardComponent.objects.filter(
            dashboard=dashboard, is_active=True, component_type="table_data"
        ).order_by("sequence")

        for component in components:
            model, table_context = self.get_table_data(component, request)
            if model:
                list_view = HorillaListView(
                    view_id=f"dashboard_component_{component.id}",
                    model=model,
                    request=request,
                    search_url=f"{reverse_lazy('horilla_dashboard:dashboard_detail_view', kwargs={'pk': component.dashboard_id})}",
                    main_url=reverse_lazy(
                        "horilla_dashboard:dashboard_detail_view",
                        kwargs={"pk": component.dashboard_id},
                    ),
                    columns=table_context.get("columns", []),
                    bulk_export_option=True,
                )
                list_view.object_list = table_context.get(
                    "queryset", model.objects.all()
                )
                return list_view.post(request, *args, **kwargs)

        return HttpResponse("No table component found to handle export", status=400)

    def get_context_data(self, **kwargs):
        """Add section, layout, components, and dashboard context for the detail view template."""
        context = super().get_context_data(**kwargs)

        section = self.request.GET.get("section")
        is_home = self.request.GET.get("is_home") == "true"
        is_default = self.object.is_default
        is_home_view = section == "home" and is_home and is_default

        dashboard = self.get_object()
        components_qs = DashboardComponent.objects.filter(
            dashboard=dashboard, is_active=True
        ).order_by("sequence")

        # Apply per-user layout order if saved (same model as default home)
        layout = DefaultHomeLayoutOrder.objects.filter(
            user=self.request.user, dashboard=dashboard
        ).first()
        if layout and isinstance(layout.order, dict):
            order = layout.order
            kpi_ids = order.get("kpi", [])
            component_ids = order.get("components", [])

            # Create ordering for KPIs
            if kpi_ids:
                kpi_order = Case(
                    *[
                        When(
                            id=int(id_val) if isinstance(id_val, str) else id_val,
                            then=pos,
                        )
                        for pos, id_val in enumerate(kpi_ids)
                    ]
                )
                components_qs = components_qs.annotate(kpi_order_field=kpi_order)

            # Create ordering for components
            if component_ids:
                comp_order = Case(
                    *[
                        When(
                            id=int(id_val) if isinstance(id_val, str) else id_val,
                            then=pos,
                        )
                        for pos, id_val in enumerate(component_ids)
                    ]
                )
                components_qs = components_qs.annotate(comp_order_field=comp_order)

            # Apply combined ordering
            if kpi_ids and component_ids:
                components_qs = components_qs.order_by(
                    "kpi_order_field", "comp_order_field", "sequence"
                )
            elif kpi_ids:
                components_qs = components_qs.order_by("kpi_order_field", "sequence")
            elif component_ids:
                components_qs = components_qs.order_by("comp_order_field", "sequence")

        user_has_custom_dashboard_layout = bool(
            layout and isinstance(layout.order, dict)
        )
        components = components_qs

        # Process KPI components
        kpi_data = []
        for component in components.filter(component_type="kpi"):
            kpi = self.get_kpi_data(component, self.request)
            if kpi:
                kpi_data.append(kpi)

        # Process chart components
        chart_data = []
        for component in components.filter(component_type="chart"):
            chart = self.get_chart_data(component, self.request)
            if chart:
                chart_data.append(chart)

        # Process table components
        table_contexts = {}
        for component in components.filter(component_type="table_data"):
            model, table_context = self.get_table_data(component, self.request)
            if model:
                table_contexts[component.id] = table_context

        session_referer_key = f"dashboard_detail_referer_{dashboard.pk}"
        current_referer = self.request.META.get("HTTP_REFERER")
        hx_current_url = self.request.headers.get("HX-Current-URL")
        stored_referer = self.request.session.get(session_referer_key)

        if hx_current_url:
            hx_path = urlparse(hx_current_url).path
            if hx_path != self.request.path:
                self.request.session[session_referer_key] = hx_current_url
                previous_url = hx_current_url
            else:
                previous_url = stored_referer or reverse_lazy(
                    "horilla_dashboard:dashboard_list_view"
                )

        elif stored_referer:
            previous_url = stored_referer
        elif current_referer and self.request.get_host() in current_referer:
            referer_path = urlparse(current_referer).path
            if referer_path != self.request.path:
                previous_url = current_referer
                self.request.session[session_referer_key] = current_referer
            else:
                previous_url = reverse_lazy("horilla_dashboard:dashboard_list_view")
        else:
            previous_url = reverse_lazy("horilla_dashboard:dashboard_list_view")

        context["previous_url"] = previous_url

        date_range = self.request.GET.get("date_range")
        if date_range == "all":
            date_range = None
        date_from = self.request.GET.get("date_from")
        date_to = self.request.GET.get("date_to")
        date_range, date_from, date_to = validate_custom_date_params(
            date_range, date_from, date_to
        )
        if date_range is None:
            date_from = None
            date_to = None

        base_url = self.request.build_absolute_uri(self.request.path).split("?")[0]
        query_params = self.request.GET.copy()
        query_params.pop("date_range", None)
        query_params.pop("date_from", None)
        query_params.pop("date_to", None)
        base_query = query_params.urlencode()
        date_range_base_url = f"{base_url}?{base_query}" if base_query else base_url

        context.update(
            {
                "current_obj": dashboard,
                "dashboard": dashboard,
                "components": components,
                "has_components": components.exists(),
                "user_has_custom_dashboard_layout": user_has_custom_dashboard_layout,
                "kpi_data": kpi_data,
                "chart_data": chart_data,
                "table_contexts": table_contexts,
                "view_id": "dashboard_components",
                "is_home_view": is_home_view,
                "section": section,
                "is_home": is_home,
                "date_range": date_range,
                "date_range_choices": DATE_RANGE_CHOICES,
                "date_range_base_url": date_range_base_url,
                "date_from": date_from,
                "date_to": date_to,
            }
        )

        return context


@method_decorator(
    permission_required_or_denied(
        ["horilla_dashboard.view_dashboard", "horilla_dashboard.view_own_dashboard"]
    ),
    name="dispatch",
)
class DashboardComponentTableDataView(LoginRequiredMixin, View):
    """
    Handle AJAX requests for table data pagination and search
    """

    def get(self, request, *args, **kwargs):
        """Handle GET request to return table data for a dashboard component."""
        component_id = kwargs.get("component_id")

        try:
            component = DashboardComponent.objects.get(
                id=component_id, component_type="table_data", is_active=True
            )
        except DashboardComponent.DoesNotExist:
            return HttpResponse("Component not found", status=404)

        # Get model
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
            return HttpResponse("Model not found", status=404)

        # Build queryset
        queryset = model.objects.all()

        conditions = component.conditions.all().order_by("sequence")

        detail_view = DashboardDetailView()
        detail_view.request = request
        queryset = detail_view.apply_conditions(queryset, conditions)

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

        # Apply sorting
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

        total_count = queryset.count()

        if total_count == 0:
            if request.headers.get("HX-Request"):
                return HttpResponse("")
            return HttpResponse("No data available")

        # Pagination
        paginator = Paginator(queryset, 10)
        page = request.GET.get("page", 1)

        try:
            page_obj = paginator.get_page(page)
        except Exception:
            if request.headers.get("HX-Request"):
                return HttpResponse("")
            return HttpResponse("Invalid page")

        has_next = page_obj.has_next()
        next_page = page_obj.next_page_number() if has_next else None

        # Build columns
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

        query_params = self.request.GET.urlencode()

        table_data_url = reverse_lazy(
            "horilla_dashboard:component_table_data",
            kwargs={"component_id": component.id},
        )

        # Create the full table_context similar to DashboardDetailView
        filtered_ids = list(queryset.values_list("id", flat=True))

        table_context = {
            "queryset": page_obj.object_list,
            "columns": columns,
            "search_url": table_data_url,
            "search_params": query_params,
            "has_next": has_next,
            "next_page": next_page,
            "page_obj": page_obj,
            "bulk_select_option": True,
            "visible_actions": [],
            "col_attrs": {},
            "table_class": True,
            "no_record_msg": f"No {model._meta.verbose_name_plural} found matching the specified criteria.",
            "header_attrs": {},
            "custom_bulk_actions": [],
            "additional_action_button": [],
            "filter_set_class": None,
            "filter_fields": [],  # You might need to populate this if needed
            "total_records_count": total_count,
            "selected_ids": filtered_ids,
            "selected_ids_json": json.dumps(filtered_ids),
            "component": component,
            "model_verbose_name": model._meta.verbose_name_plural,
            "view_id": f"dashboard_component_{component.id}",
            "app_label": model._meta.app_label,
            "model_name": model._meta.model_name,
        }

        if request.headers.get("HX-Request"):
            return render(request, "list_view.html", table_context)

        context = {
            "current_obj": component.dashboard,
            "dashboard": component.dashboard,
            "components": DashboardComponent.objects.filter(
                dashboard=component.dashboard, is_active=True
            ),
            "has_components": True,
            "": 100,
            "table_contexts": {component.id: table_context},
        }

        return render(request, "list_view.html", context)

    def post(self, request, *args, **kwargs):
        """Handle bulk operations"""
        self.request = request
        component_id = kwargs.get("component_id")

        try:
            component = DashboardComponent.objects.get(
                id=component_id, component_type="table_data", is_active=True
            )
        except DashboardComponent.DoesNotExist:
            return HttpResponse("Component not found", status=404)

        dashboard_view = DashboardDetailView()
        model, table_context = dashboard_view.get_table_data(component, request)

        if model:
            list_view = HorillaListView(
                model=model,
                request=request,
                view_id=f"table_{component.id}",
                search_url=reverse_lazy(
                    "horilla_dashboard:component_table_data",
                    kwargs={"component_id": component.id},
                ),
                main_url=reverse_lazy(
                    "horilla_dashboard:dashboard_detail_view",
                    kwargs={"pk": component.dashboard_id},
                ),
                columns=table_context.get("columns", []),
                bulk_export_option=True,
            )
            list_view.object_list = table_context.get("queryset", model.objects.all())
            return list_view.post(request, *args, **kwargs)

        return HttpResponse("No table component found to handle export", status=400)


@method_decorator(htmx_required, name="dispatch")
class DashboardComponentFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Form view to dashboard component
    """

    template_name = "dashboard_component_form.html"
    model = DashboardComponent
    form_class = DashboardCreateForm
    condition_fields = ["field", "operator", "value"]
    condition_model = ComponentCriteria
    condition_related_name = "conditions"
    condition_order_by = ["sequence"]
    content_type_field = (
        "module"  # Enable automatic model_name extraction from module field
    )
    condition_hx_include = (
        "#id_module"  # Include module field when adding condition rows
    )
    hidden_fields = [
        "company",
        "config",
        "is_active",
        "dashboard",
        "sequence",
        "component_owner",
        "reports",
    ]
    full_width_fields = ["name"]
    save_and_new = False

    def get_initial(self):
        """Set initial dashboard, company, and component_owner from request."""
        initial = super().get_initial()
        dashboard_id = self.request.GET.get("dashboard") or self.request.POST.get(
            "dashboard"
        )

        if dashboard_id:
            dashboard = Dashboard.objects.get(id=dashboard_id)
            initial["dashboard"] = dashboard
        company = (
            getattr(_thread_local, "request", None).active_company
            if hasattr(_thread_local, "request")
            else self.request.user.company
        )
        initial["company"] = company
        initial["component_owner"] = self.request.user

        initial.update(self.request.GET.dict())
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        model_name = (
            self.request.GET.get("model_name")
            or self.request.POST.get("model_name")
            or self.request.GET.get("module")
            or self.request.POST.get("module")
        )

        # If module is a HorillaContentType ID, convert it to model_name
        if model_name and model_name.isdigit():
            try:
                content_type = HorillaContentType.objects.get(pk=model_name)
                model_name = content_type.model
            except Exception:
                pass

        if model_name:
            if "initial" not in kwargs:
                kwargs["initial"] = {}
            kwargs["initial"]["model_name"] = model_name

        kwargs["condition_model"] = ComponentCriteria
        kwargs["request"] = self.request

        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        form = context.get("form")
        if form and hasattr(form, "instance") and form.instance.module:
            context["module"] = form.instance.module
        elif self.request.method == "GET" and self.request.GET.get("module"):
            context["module"] = self.request.GET.get("module")
        else:
            context["module"] = ""

        return context

    @cached_property
    def form_url(self):
        """Determine form action URL based on whether creating or updating."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")

        if pk:
            url = reverse_lazy("horilla_dashboard:component_update", kwargs={"pk": pk})
        else:
            url = reverse_lazy("horilla_dashboard:component_create")

        dashboard_id = self.request.GET.get("dashboard")
        if dashboard_id:
            final_url = f"{url}?dashboard={dashboard_id}"
        else:
            final_url = str(url)

        return final_url

    def get(self, request, *args, **kwargs):
        component_id = self.kwargs.get("pk")
        if request.user.has_perm(
            "horilla_dashboard.change_dashboard"
        ) or request.user.has_perm("horilla_dashboard.add_dashboard"):
            return super().get(request, *args, **kwargs)

        if component_id:
            component = get_object_or_404(DashboardComponent, pk=component_id)
            if component.component_owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "error/403.html")

    def form_valid(self, form):
        """Handle form submission and ensure proper file path"""
        instance = form.save(commit=False)

        if "icon" in self.request.FILES:
            icon_file = self.request.FILES["icon"]
            instance.icon = icon_file

        return super().form_valid(form)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_dashboard.add_dashboard"), name="dispatch"
)
class ModuleFieldChoicesView(View):
    """
    Class-based view to return field choices for a selected module via HTMX.
    """

    def get(self, request, *args, **kwargs):
        """
        Handle GET request to return a <select> element with field choices.
        """
        module = request.GET.get("module")
        row_id = request.GET.get("row_id", "0")
        # Restrict row_id to safe identifier chars to prevent XSS when used in HTML
        if not row_id.isdigit():
            row_id = "0"

        field_name = f"field_{row_id}"
        field_id = f"id_field_{row_id}"

        if module and module.isdigit():
            try:
                content_type = HorillaContentType.objects.get(pk=module)
                module = content_type.model
            except HorillaContentType.DoesNotExist:
                pass

        if not module:
            return render(
                request,
                "partials/field_select_empty.html",
                {"field_name": field_name, "field_id": field_id},
            )
            # return HttpResponse(
            #     f'<select name="{field_name}" id="{field_id}" class="js-example-basic-single headselect"><option value="">---------</option></select>'
            # )

        try:
            model = None
            for app_config in apps.get_app_configs():
                try:
                    model = apps.get_model(
                        app_label=app_config.label, model_name=module.lower()
                    )
                    break
                except LookupError:
                    continue
            if not model:
                return render(
                    request,
                    "partials/field_select_empty.html",
                    {"field_name": field_name, "field_id": field_id},
                )
        except Exception:
            return render(
                request,
                "partials/field_select_empty.html",
                {"field_name": field_name, "field_id": field_id},
            )
        model_fields = []
        for field in model._meta.get_fields():
            if field.concrete or field.is_relation:
                verbose_name = getattr(field, "verbose_name", field.name)
                if field.is_relation:
                    verbose_name = f"{verbose_name}"
                model_fields.append((field.name, verbose_name))

        field_choices = [("", "Select Field")] + model_fields

        return render(
            request,
            "partials/module_field_select.html",
            {
                "field_name": field_name,
                "field_id": field_id,
                "row_id": row_id,
                "model_name": module,
                "field_choices": field_choices,
            },
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_dashboard.add_dashboard"), name="dispatch"
)
class ColumnFieldChoicesView(View):
    """
    View to return metric field choices for a selected module via HTMX.
    """

    def get(self, request, *args, **kwargs):
        """Handle GET request to return a <select> element with column field choices."""
        module = request.GET.get("module")

        if module and module.isdigit():
            try:
                content_type = HorillaContentType.objects.get(pk=module)
                module = content_type.model
            except HorillaContentType.DoesNotExist:
                pass

        if not module:
            return HttpResponse(
                '<select name="columns" id="id_columns" class="js-example-basic-multiple headselect" multiple ><option value="">---------</option></select>'
            )

        try:
            model = None
            for app_config in apps.get_app_configs():
                try:
                    model = apps.get_model(
                        app_label=app_config.label, model_name=module.lower()
                    )
                    break
                except LookupError:
                    continue

            if not model:
                return render(
                    request,
                    "partials/column_field_select_empty.html",
                )
        except Exception:
            return render(
                request,
                "partials/column_field_select_empty.html",
            )

        column_fields = []
        for field in model._meta.get_fields():
            if field.concrete and not field.is_relation:
                field_name = field.name
                field_label = field.verbose_name or field.name

                if hasattr(field, "get_internal_type"):
                    field_type = field.get_internal_type()
                    if field_type in DISPLAYABLE_FIELD_TYPES:
                        column_fields.append((field_name, field_label))
                    elif hasattr(field, "choices") and field.choices:
                        column_fields.append((field_name, f"{field_label}"))
            # Include ForeignKey fields for grouping
            elif hasattr(field, "related_model") and field.many_to_one:
                field_name = field.name
                field_label = field.verbose_name or field.name
                column_fields.append((field_name, f"{field_label}"))

        field_choices = [("", "Add Columns")] + column_fields

        return render(
            request,
            "partials/column_field_select.html",
            {"field_choices": field_choices},
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_dashboard.add_dashboard"), name="dispatch"
)
class GroupingFieldChoicesView(View):
    """
    View to return grouping field choices for a selected module via HTMX.
    """

    def get(self, request, *args, **kwargs):
        """Handle GET request to return a <select> element with grouping field choices."""
        module = request.GET.get("module")

        if module and module.isdigit():
            try:
                content_type = HorillaContentType.objects.get(pk=module)
                module = content_type.model
            except HorillaContentType.DoesNotExist:
                pass

        if not module:
            return render(
                request,
                "partials/grouping_field_select_empty.html",
            )

        try:
            model = None
            for app_config in apps.get_app_configs():
                try:
                    model = apps.get_model(
                        app_label=app_config.label, model_name=module.lower()
                    )
                    break
                except LookupError:
                    continue

            if not model:
                return render(
                    request,
                    "partials/grouping_field_select_empty.html",
                )
        except Exception:
            return render(
                request,
                "partials/grouping_field_select_empty.html",
            )

        # Get fields suitable for grouping
        grouping_fields = []
        for field in model._meta.get_fields():
            if field.concrete and not field.is_relation:
                field_name = field.name
                field_label = field.verbose_name or field.name

                if hasattr(field, "get_internal_type"):
                    field_type = field.get_internal_type()
                    if field_type in DISPLAYABLE_FIELD_TYPES:
                        grouping_fields.append((field_name, field_label))
                    elif hasattr(field, "choices") and field.choices:
                        grouping_fields.append((field_name, f"{field_label}"))

            # Include ForeignKey fields for grouping
            elif hasattr(field, "related_model") and field.many_to_one:
                field_name = field.name
                field_label = field.verbose_name or field.name
                grouping_fields.append((field_name, f"{field_label}"))

        field_choices = [("", "Select Grouping Field")] + grouping_fields

        return render(
            request,
            "partials/grouping_field_select.html",
            {"field_choices": field_choices},
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_dashboard.add_dashboard"), name="dispatch"
)
class SecondaryGroupingFieldChoicesView(View):
    """
    View to return secondary grouping field choices for a selected module via HTMX.
    """

    def get(self, request, *args, **kwargs):
        """Handle GET request to return a <select> element with secondary grouping field choices."""
        module = request.GET.get("module")

        if module and module.isdigit():
            try:
                content_type = HorillaContentType.objects.get(pk=module)
                module = content_type.model
            except HorillaContentType.DoesNotExist:
                pass

        if not module:
            return render(
                request,
                "partials/secondary_grouping_field_select_empty.html",
            )

        try:
            model = None
            for app_config in apps.get_app_configs():
                try:
                    model = apps.get_model(
                        app_label=app_config.label, model_name=module.lower()
                    )
                    break
                except LookupError:
                    continue

            if not model:
                return render(
                    request,
                    "partials/secondary_grouping_field_select_empty.html",
                )
        except Exception:
            return render(
                request,
                "partials/secondary_grouping_field_select_empty.html",
            )

        grouping_fields = []
        for field in model._meta.get_fields():
            if field.concrete and not field.is_relation:
                field_name = field.name
                field_label = field.verbose_name or field.name

                if hasattr(field, "get_internal_type"):
                    field_type = field.get_internal_type()
                    if field_type in DISPLAYABLE_FIELD_TYPES:
                        grouping_fields.append((field_name, field_label))
                    elif hasattr(field, "choices") and field.choices:
                        grouping_fields.append((field_name, f"{field_label}"))

            elif hasattr(field, "related_model") and field.many_to_one:
                field_name = field.name
                field_label = field.verbose_name or field.name
                grouping_fields.append((field_name, f"{field_label}"))

        field_choices = [("", "Select Secondary Grouping Field")] + grouping_fields

        return render(
            request,
            "partials/secondary_grouping_field_select.html",
            {"field_choices": field_choices},
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_dashboard.add_dashboard"), name="dispatch"
)
class ChartPreviewView(View):
    """View to return a preview of the chart based on selected type and component type."""

    def get(self, request, *args, **kwargs):
        """Handle GET request to return chart preview HTML."""
        chart_type = request.GET.get("chart_type", "")
        component_type = request.GET.get("component_type", "")

        if component_type is None or component_type == "None":
            component_type = ""
        if chart_type is None or chart_type == "None":
            chart_type = ""

        if component_type == "kpi":
            html = format_html(
                """
                    <div class="bg-white rounded-lg border border-primary-300 p-4 shadow-sm" style="width: 30vh;">
                        <div class="flex flex-col space-y-2">
                            <h3 class="text-sm font-medium text-gray-500">{}</h3>
                            <div class="flex items-baseline space-x-2">
                                <span class="text-2xl font-bold text-gray-900">{}</span>
                                <span class="text-sm font-medium text-green-600 bg-green-50 px-2 py-1 rounded">{}</span>
                            </div>
                        </div>
                    </div>
                    """,
                "Total",
                "$574.34",
                "+23%",
            )
            return HttpResponse(html)

        if component_type == "table_data":
            html = """
            <div class="overflow-x-auto">
                <table class="min-w-full bg-white border border-dark-50">
                    <thead>
                        <tr class="border border-dark-50">
                            <th class="py-2 px-4 border border-dark-50">Company Name</th>
                            <th class="py-2 px-4 border border-dark-50">Email</th>
                            <th class="py-2 px-4 border border-dark-50">Contact Number</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td class="py-2 px-4 border border-dark-50">Company A</td>
                            <td class="py-2 px-4 border border-dark-50">companya@example.com</td>
                            <td class="py-2 px-4 border border-dark-50">9876543210</td>
                        </tr>
                        <tr>
                            <td class="py-2 px-4 border border-dark-50">Company B</td>
                            <td class="py-2 px-4 border border-dark-50">companyb@example.com</td>
                            <td class="py-2 px-4 border border-dark-50">9876543211</td>
                        </tr>
                        <tr>
                            <td class="py-2 px-4 border border-dark-50">Company C</td>
                            <td class="py-2 px-4 border border-dark-50">companyc@example.com</td>
                            <td class="py-2 px-4 border border-dark-50">9876543212</td>
                        </tr>
                        <tr>
                            <td class="py-2 px-4 border border-dark-50">Company D</td>
                            <td class="py-2 px-4 border border-dark-50">companyd@example.com</td>
                            <td class="py-2 px-4 border border-dark-50">9876543213</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            """
            return HttpResponse(html)

        if component_type == "chart" or (not component_type and chart_type):
            sample_data = {
                "column": {
                    "labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                    "data": [120, 200, 150, 80, 70, 110, 130],
                    "labelField": "Sample Data",
                },
                "bar": {
                    "labels": ["Category A", "Category B", "Category C", "Category D"],
                    "data": [12, 19, 15, 17],
                    "labelField": "Sample Data",
                },
                "pie": {
                    "labels": ["Sample A", "Sample B", "Sample C", "Sample D"],
                    "data": [30, 25, 25, 20],
                    "labelField": "Sample Data",
                },
                "donut": {
                    "labels": ["Sample 1", "Sample 2", "Sample 3"],
                    "data": [40, 35, 25],
                    "labelField": "Sample Data",
                },
                "line": {
                    "labels": ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5"],
                    "data": [10, 25, 15, 30, 28],
                    "labelField": "Sample Data",
                },
                "stacked_vertical": {
                    "stackedData": {
                        "categories": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                        "series": [
                            {"name": "Series 1", "data": [10, 20, 15, 25, 30]},
                            {"name": "Series 2", "data": [5, 10, 8, 12, 15]},
                        ],
                    },
                    "labelField": "Sample Data",
                    "hasMultipleGroups": True,
                },
                "stacked_horizontal": {
                    "stackedData": {
                        "categories": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                        "series": [
                            {"name": "Series 1", "data": [10, 20, 15, 25, 30]},
                            {"name": "Series 2", "data": [5, 10, 8, 12, 15]},
                        ],
                    },
                    "labelField": "Sample Data",
                    "hasMultipleGroups": True,
                },
                "funnel": {
                    "labels": [
                        "Stage 1",
                        "Satge 2",
                        "Stage 3",
                        "Stage 4",
                        "Stage 5",
                    ],
                    "data": [100, 75, 50, 30, 20],
                    "labelField": "Sample Data",
                },
            }

            config = sample_data.get(chart_type)
            if config:
                chart_config = {"type": chart_type, **config}
                chart_config_json = json.dumps(chart_config)
                html = f"""
                <div id="preview-wrapper" class="w-full h-full relative overflow-hidden">
                    <div id="preview-chart-{chart_type}" class="w-full h-full" style="min-height: 200px;"></div>
                </div>
                <script>
                (function() {{
                    const chartDom = document.getElementById('preview-chart-{chart_type}');
                    if (chartDom && typeof EChartsConfig !== 'undefined' && typeof echarts !== 'undefined') {{
                        const previewKey = 'preview-chart-{chart_type}';
                        if (window.chartInstances && window.chartInstances[previewKey]) {{
                            try {{ window.chartInstances[previewKey].instance.dispose(); }} catch (e) {{}}
                        }}
                        const myChart = echarts.init(chartDom);
                        const config = {chart_config_json};
                        const option = EChartsConfig.getChartOption(config);
                        myChart.setOption(option);
                        if (typeof window.chartInstances === 'undefined') window.chartInstances = {{}};
                        window.chartInstances[previewKey] = {{ instance: myChart, config: config }};
                    }}
                }})();
                </script>
                """
                return HttpResponse(html)

        message = (
            "Select component type to see preview"
            if not component_type and not chart_type
            else (
                f"Preview for {component_type} component"
                if component_type and component_type != "chart" and not chart_type
                else (
                    "Select chart type to see preview"
                    if component_type == "chart" and not chart_type
                    else "Chart type not supported"
                )
            )
        )
        return HttpResponse(
            format_html(
                '<div class="text-gray-500 text-sm flex items-center justify-center h-full">{}</div>',
                message,
            )
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["horilla_dashboard.view_dashboard", "horilla_dashboard.view_own_dashboard"]
    ),
    name="dispatch",
)
class DashboardComponentChartView(View):
    """
    View to render chart data for dashboard components using ECharts.
    Handles chart components with ECharts and KPIs with custom HTML.
    """

    def apply_conditions(self, queryset, conditions):
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
                            continue

                    elif field_type == "BooleanField":
                        if value.lower() in ["true", "1", "yes"]:
                            converted_value = True
                        elif value.lower() in ["false", "0", "no"]:
                            converted_value = False
                        else:
                            continue

                    elif field_type == "ForeignKey":
                        try:
                            converted_value = int(value)
                        except (ValueError, TypeError):
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
                    # Handle comma-separated values
                    values = [v.strip() for v in value.split(",")]
                    queryset = queryset.filter(**{f"{field}__in": values})

                elif operator == "not_in":
                    values = [v.strip() for v in value.split(",")]
                    queryset = queryset.exclude(**{f"{field}__in": values})

            except Exception as e:
                logger.error(
                    "Error applying condition %s %s %s: %s", field, operator, value, e
                )
                continue

        return queryset

    def get_kpi_data(self, component):
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
            queryset = get_queryset_for_module(self.request.user, model)

            conditions = component.conditions.all().order_by("sequence")
            queryset = self.apply_conditions(queryset, conditions)

            date_range = self.request.GET.get("date_range")
            if date_range and (
                str(date_range) in [str(d) for d in DATE_RANGE_CHOICES]
                or date_range == "custom"
            ):
                date_from = (
                    self.request.GET.get("date_from")
                    if date_range == "custom"
                    else None
                )
                date_to = (
                    self.request.GET.get("date_to") if date_range == "custom" else None
                )
                queryset = apply_date_range_to_queryset(
                    queryset, model, date_range, date_from=date_from, date_to=date_to
                )

            value = queryset.count()

            section_info = get_section_info_for_model(model)

            metric_label = (
                f"{component.metric_type.title() if component.metric_type else 'Count'}"
            )

            base_url = section_info["url"]
            if conditions.exists():
                query_params = [
                    ("section", section_info["section"]),
                    ("apply_filter", "true"),
                ]

                for condition in conditions:

                    operator = (
                        "exact"
                        if condition.operator == "equals"
                        else condition.operator
                    )

                    query_params.append(("field", condition.field))
                    query_params.append(("operator", operator))
                    query_params.append(("value", condition.value))

                query = urlencode(query_params, doseq=True)
                filtered_url = f"{base_url}?{query}"
            else:
                filtered_url = f"{base_url}?section={section_info['section']}"

            return {
                "value": float(value),
                "url": filtered_url,
                "section": section_info["section"],
                "label": f"{metric_label} of {module_name.title()}",
            }
        except Exception:
            return None

    def get_chart_data(self, component):
        """
        Retrieve chart data based on component configuration.
        Handles only chart-type components. Always uses Count aggregation.
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

        if not model or component.component_type != "chart":
            return None

        try:
            queryset = get_queryset_for_module(self.request.user, model)
            conditions = component.conditions.all()

            date_range = self.request.GET.get("date_range")
            if date_range and (
                str(date_range) in [str(d) for d in DATE_RANGE_CHOICES]
                or date_range == "custom"
            ):
                date_from = (
                    self.request.GET.get("date_from")
                    if date_range == "custom"
                    else None
                )
                date_to = (
                    self.request.GET.get("date_to") if date_range == "custom" else None
                )
                queryset = apply_date_range_to_queryset(
                    queryset, model, date_range, date_from=date_from, date_to=date_to
                )

            is_stacked_chart = component.chart_type in [
                "stacked_vertical",
                "stacked_horizontal",
            ]

            x_axis_label = (
                component.grouping_field.replace("_", " ").title()
                if component.grouping_field
                else "Category"
            )

            if component.grouping_field:
                field = model._meta.get_field(component.grouping_field)

                if is_stacked_chart and component.secondary_grouping:
                    return self.get_stacked_chart_data(
                        queryset, component, conditions, field, x_axis_label, model
                    )

                queryset = self.apply_conditions(queryset, conditions)

                # Always use Count for charts
                if field.is_relation and hasattr(field.remote_field.model, "name"):
                    queryset = queryset.values(
                        f"{component.grouping_field}__name",
                        f"{component.grouping_field}_id",
                    ).annotate(value=Count("id"))
                else:
                    if field.is_relation:
                        queryset = queryset.values(
                            component.grouping_field, f"{component.grouping_field}_id"
                        ).annotate(value=Count("id"))
                    else:
                        queryset = queryset.values(component.grouping_field).annotate(
                            value=Count("id")
                        )

                labels = []
                data = []
                urls = []
                section_info = get_section_info_for_model(model)

                for item in queryset:
                    # Get the raw label value
                    label = item.get(
                        f"{component.grouping_field}__name"
                        if field.is_relation
                        and hasattr(field.remote_field.model, "name")
                        else component.grouping_field
                    )

                    # Convert choice field keys to display values
                    try:
                        if hasattr(field, "choices") and field.choices:
                            original_label = label
                            for choice_value, choice_label in field.choices:
                                if choice_value == original_label:
                                    label = choice_label
                                    break
                        elif field.is_relation and label is not None:
                            # For FK fields without 'name' attribute, get string representation
                            if not hasattr(field.remote_field.model, "name"):
                                try:
                                    related_obj = field.remote_field.model.objects.get(
                                        pk=label
                                    )
                                    label = str(related_obj)
                                except Exception:
                                    pass
                    except Exception:
                        pass

                    if isinstance(label, (list, dict)):
                        label = str(label)
                    elif label is None:
                        label = "None"

                    labels.append(str(label))
                    data.append(float(item["value"]))

                    # For filter URL, use the actual filter value (ID for FK, key for choices)
                    filter_value = label
                    if field.is_relation:
                        filter_value = item.get(f"{component.grouping_field}_id")
                    else:
                        filter_value = item.get(component.grouping_field)

                    query = urlencode(
                        {
                            "section": section_info["section"],
                            "apply_filter": "true",
                            "field": component.grouping_field,
                            "operator": "exact",
                            "value": filter_value,
                        }
                    )
                    urls.append(f"{section_info['url']}?{query}")

                return {
                    "labels": labels,
                    "data": data,
                    "urls": urls,
                    "labelField": component.grouping_field.replace("_", " ").title(),
                    "x_axis_label": x_axis_label,
                    "is_condition_based": conditions.exists(),
                }

            return None
        except Exception:
            return None

    def get_stacked_chart_data(
        self, queryset, component, conditions, field, x_axis_label, model
    ):
        """Handle stacked chart data - always uses Count aggregation"""
        try:
            queryset = self.apply_conditions(queryset, conditions)

            section_info = get_section_info_for_model(model)

            if field.is_relation and hasattr(field.remote_field.model, "name"):
                categories = list(
                    queryset.values_list(f"{component.grouping_field}__name", flat=True)
                    .distinct()
                    .order_by(f"{component.grouping_field}__name")
                )
            else:
                categories = list(
                    queryset.values_list(component.grouping_field, flat=True)
                    .distinct()
                    .order_by(component.grouping_field)
                )

            try:
                if hasattr(field, "choices") and field.choices:
                    category_display = {}
                    for choice_value, choice_label in field.choices:
                        category_display[choice_value] = choice_label
                    categories = [
                        (
                            category_display.get(cat, str(cat))
                            if cat is not None
                            else "None"
                        )
                        for cat in categories
                        if cat is not None
                    ]
                else:
                    categories = [
                        str(cat) if cat is not None else "None"
                        for cat in categories
                        if cat is not None
                    ]
            except Exception:
                categories = [
                    str(cat) if cat is not None else "None"
                    for cat in categories
                    if cat is not None
                ]

            secondary_field = (
                model._meta.get_field(component.secondary_grouping)
                if component.secondary_grouping
                else None
            )
            if not secondary_field:
                return None

            if secondary_field.is_relation and hasattr(
                secondary_field.remote_field.model, "name"
            ):
                secondary_values = list(
                    queryset.values_list(
                        f"{component.secondary_grouping}__name", flat=True
                    ).distinct()
                )
            else:
                secondary_values = list(
                    queryset.values_list(
                        component.secondary_grouping, flat=True
                    ).distinct()
                )

            secondary_values = [val for val in secondary_values if val is not None]

            if not secondary_values:
                return None

            series_data = []

            for secondary_value in secondary_values:
                display_value = secondary_value

                if secondary_field.is_relation and hasattr(
                    secondary_field.remote_field.model, "name"
                ):
                    related_obj = secondary_field.remote_field.model.objects.filter(
                        name=secondary_value
                    ).first()
                    if related_obj:
                        display_value = str(related_obj)
                elif isinstance(secondary_field, ForeignKey):
                    related_obj = secondary_field.remote_field.model.objects.filter(
                        pk=secondary_value
                    ).first()
                    if related_obj:
                        display_value = str(related_obj)
                elif hasattr(secondary_field, "choices") and secondary_field.choices:
                    for choice_value, choice_label in secondary_field.choices:
                        if choice_value == secondary_value:
                            display_value = choice_label
                            break

                filtered_queryset = queryset.filter(
                    **{component.secondary_grouping: secondary_value}
                )

                if field.is_relation and hasattr(field.remote_field.model, "name"):
                    grouped_data = filtered_queryset.values(
                        f"{component.grouping_field}__name"
                    ).annotate(value=Count("id"))
                    grouped_dict = {
                        item[f"{component.grouping_field}__name"]: item["value"]
                        for item in grouped_data
                    }
                else:
                    grouped_data = filtered_queryset.values(
                        component.grouping_field
                    ).annotate(value=Count("id"))
                    grouped_dict = {
                        str(item[component.grouping_field]): item["value"]
                        for item in grouped_data
                    }

                series_values = []
                for category in categories:
                    series_values.append(float(grouped_dict.get(category, 0)))

                series_data.append(
                    {
                        "name": str(display_value),
                        "data": series_values,
                    }
                )

            urls = []
            if field.is_relation and hasattr(field.remote_field.model, "name"):
                original_categories = list(
                    queryset.values_list(f"{component.grouping_field}_id", flat=True)
                    .distinct()
                    .order_by(f"{component.grouping_field}__name")
                )
            else:
                original_categories = list(
                    queryset.values_list(component.grouping_field, flat=True)
                    .distinct()
                    .order_by(component.grouping_field)
                )
                original_categories = [
                    cat for cat in original_categories if cat is not None
                ]

            for filter_value in original_categories:
                query = urlencode(
                    {
                        "section": section_info["section"],
                        "apply_filter": "true",
                        "field": component.grouping_field,
                        "operator": "exact",
                        "value": filter_value,
                    }
                )
                urls.append(f"{section_info['url']}?{query}")

            return {
                "labels": categories,
                "data": [],
                "urls": urls,
                "stackedData": {"categories": categories, "series": series_data},
                "labelField": component.grouping_field.replace("_", " ").title(),
                "x_axis_label": x_axis_label,
                "hasMultipleGroups": True,
                "is_condition_based": conditions.exists(),
            }

        except Exception as e:
            messages.error(self.request, e)
            return None

    def get_report_chart_data(self, component):
        """
        Retrieve chart data for report-based components.
        Always uses Count aggregation.
        """
        try:
            report = component.reports
            if not report:
                logger.warning("No report found for component %s", component.id)
                return None

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
                logger.warning(
                    "Model not found for component %s, module: %s",
                    component.id,
                    component.module,
                )
                return None

            if not component.grouping_field:
                logger.warning("No grouping field for component %s", component.id)
                return None

            queryset = get_queryset_for_module(self.request.user, model)

            conditions = component.conditions.all().order_by("sequence")
            queryset = self.apply_conditions(queryset, conditions)

            if queryset.count() == 0:
                logger.warning("Empty queryset for component %s", component.id)
                return None

            field = model._meta.get_field(component.grouping_field)

            # Check if it's a stacked chart
            is_stacked_chart = component.chart_type in [
                "stacked_vertical",
                "stacked_horizontal",
            ]

            x_axis_label = (
                component.grouping_field.replace("_", " ").title()
                if component.grouping_field
                else "Category"
            )

            # Handle stacked charts
            if is_stacked_chart and component.secondary_grouping:
                logger.info("Processing stacked chart for component %s", component.id)
                return self.get_stacked_chart_data(
                    queryset, component, conditions, field, x_axis_label, model
                )

            # Handle single grouping charts - ALWAYS USE COUNT
            if field.is_relation and hasattr(field.remote_field.model, "name"):
                aggregated_data = queryset.values(
                    f"{component.grouping_field}__name",
                    f"{component.grouping_field}_id",
                ).annotate(value=Count("id"))
                field_name = f"{component.grouping_field}__name"
                id_field_name = f"{component.grouping_field}_id"
            else:
                # Report charts always use Count aggregation
                aggregated_data = queryset.values(component.grouping_field).annotate(
                    value=Count("id")
                )
                field_name = component.grouping_field
                id_field_name = None

            labels = []
            data = []
            urls = []
            section_info = get_section_info_for_model(model)

            for item in aggregated_data:
                if field.is_relation and id_field_name:
                    filter_value = item.get(id_field_name)  # Use ID for relations
                    label = item.get(field_name)
                else:
                    filter_value = item.get(field_name)
                    label = filter_value

                # Handle choice fields
                try:
                    field_obj = model._meta.get_field(component.grouping_field)
                    if hasattr(field_obj, "choices") and field_obj.choices:
                        for choice_value, choice_label in field_obj.choices:
                            if choice_value == label:
                                label = choice_label
                                break
                except Exception:
                    pass

                if isinstance(label, (list, dict)):
                    label = str(label)
                elif label is None:
                    label = "None"
                else:
                    label = str(label)

                labels.append(label)
                data.append(float(item["value"]) if item["value"] is not None else 0)

                query = urlencode(
                    {
                        "section": section_info["section"],
                        "apply_filter": "true",
                        "field": component.grouping_field,
                        "operator": "exact",
                        "value": filter_value,
                    }
                )
                urls.append(f"{section_info['url']}?{query}")

            return {
                "labels": labels,
                "data": data,
                "urls": urls,
                "labelField": component.grouping_field.replace("_", " ").title(),
                "x_axis_label": x_axis_label,
                "is_condition_based": conditions.exists(),
                "is_from_report": True,
                "report_name": report.name,
            }
        except Exception as e:
            logger.error(
                "Failed to generate report chart for component %s: %s",
                component.id,
                e,
                exc_info=True,
            )
            return None

    def get(self, request, *args, **kwargs):
        """
        Handle GET request to render the chart or KPI component.
        Uses ECharts for charts and custom HTML for KPIs with modern card design.
        """
        component_id = kwargs.get("component_id")
        try:
            component = DashboardComponent.objects.get(id=component_id)
            if component.component_type == "kpi":
                kpi_data = self.get_kpi_data(component)
                if not kpi_data:
                    return HttpResponse(
                        '<div class="text-gray-500 text-sm flex items-center justify-center h-full">No KPI data available</div>'
                    )

                bg_colors = [
                    "bg-[#FFF3E0]",  # Light orange
                    "bg-[#E8F5E8]",  # Light green
                    "bg-[#FFE1F4]",  # Light pink
                    "bg-[#E3F2FD]",  # Light blue
                    "bg-[#F3E5F5]",  # Light purple
                    "bg-[#E0F2F1]",  # Light teal
                ]

                icon_colors = [
                    "text-orange-500",  # Orange
                    "text-green-500",  # Green
                    "text-pink-500",  # Pink
                    "text-blue-500",  # Blue
                    "text-purple-500",  # Purple
                    "text-teal-500",  # Teal
                ]

                bg_color = bg_colors[component.id % len(bg_colors)]
                icon_color = icon_colors[component.id % len(icon_colors)]

                # Format value - KPIs always show count
                formatted_value = f"{int(kpi_data['value']):,}"

                referer = request.META.get("HTTP_REFERER", "")
                is_home_view = "section=home" in referer

                context = {
                    "component_id": component_id,
                    "component_name": component.name,
                    "kpi_url": kpi_data["url"],
                    "section": kpi_data["section"],
                    "formatted_value": formatted_value,
                    "bg_color": bg_color,
                    "icon_color": icon_color,
                    "icon_url": component.icon.url if component.icon else None,
                    "is_home_view": is_home_view,
                    "query_string": request.GET.urlencode(),
                }

                return render(request, "kpi_components.html", context)

            if component.component_type == "chart":
                if component.reports:
                    chart_data = self.get_report_chart_data(component)
                else:
                    chart_data = self.get_chart_data(component)

                if not chart_data:
                    return HttpResponse(
                        '<div class="text-gray-500 text-sm flex items-center justify-center h-full">No data available</div>'
                    )

                conditions = component.conditions.all()
                if conditions.exists():
                    condition_text = "Conditions: " + ", ".join(
                        [
                            f"{cond.field} {cond.get_operator_display()} {cond.value}"
                            for cond in conditions
                        ]
                    )
                    chart_data["title"] = {
                        "subtext": condition_text,
                        "subtextStyle": {"fontSize": 12},
                        "bottom": 0,
                    }

                chart_config = {"type": component.chart_type, **chart_data}
                chart_config_json = json.dumps(chart_config)
                html = f"""
                <div id="component-chart-{component.id}" class="w-full h-full" style="min-height: 200px;"></div>
                <script>
                (function() {{
                    const chartDom = document.getElementById('component-chart-{component.id}');
                    if (chartDom && typeof EChartsConfig !== 'undefined' && typeof echarts !== 'undefined') {{
                        const compKey = 'dashboard-component-{component.id}';
                        if (window.chartInstances && window.chartInstances[compKey]) {{
                            try {{ window.chartInstances[compKey].instance.dispose(); }} catch (e) {{}}
                        }}
                        const myChart = echarts.init(chartDom);
                        const config = {chart_config_json};
                        const option = EChartsConfig.getChartOption(config);
                        myChart.setOption(option);
                        EChartsConfig.attachClickHandler(myChart, config.urls);
                        if (typeof window.chartInstances === 'undefined') window.chartInstances = {{}};
                        window.chartInstances[compKey] = {{ instance: myChart, config: config }};
                    }}
                }})();
                </script>
                """
                return HttpResponse(html)
            return None

        except DashboardComponent.DoesNotExist:
            return HttpResponse(
                '<div class="text-gray-500 text-sm flex items-center justify-center h-full">Component not found</div>'
            )
        except Exception as e:
            return HttpResponse(
                format_html(
                    '<div class="text-gray-500 text-sm flex items-center justify-center h-full">Error: {} </div>',
                    str(e),
                )
            )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_dashboard.delete_dashboard", modal=True),
    name="dispatch",
)
class ComponentDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View to handle deletion of dashboard components."""

    model = DashboardComponent

    def get_post_delete_response(self):
        return HttpResponse("<script>htmx.trigger('#reloadButton','click');</script>")


@method_decorator(htmx_required, name="dispatch")
class AddToDashboardForm(LoginRequiredMixin, HorillaSingleFormView):
    """
    View to handle adding a component to another dashboard.
    """

    model = DashboardComponent
    modal_height = False
    form_title = _("Move to Dashboard")
    fields = ["dashboard"]
    full_width_fields = ["dashboard"]
    save_and_new = False

    def get_form_kwargs(self):
        """
        Pass the request to the form for queryset filtering and validation.
        """
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def get_initial(self):
        """Set initial dashboard from component_id when moving component."""
        initial = super().get_initial()
        component_id = self.kwargs.get("component_id")
        if component_id:
            component = DashboardComponent.objects.get(
                pk=self.kwargs.get("component_id")
            )
            initial["dashboard"] = component.dashboard
        return initial

    def get_form(self, form_class=None):
        """Add widget attrs and restrict dashboard queryset for non-superusers."""
        form = super().get_form(form_class)
        user = getattr(self.request, "user", None)
        if user:
            form.fields["dashboard"].widget.attrs.update(
                {
                    "class": "js-example-basic-single",
                }
            )
            if not user.is_superuser:
                form.fields["dashboard"].queryset = Dashboard.objects.filter(
                    dashboard_owner=user
                )
        return form

    @cached_property
    def form_url(self):
        """Determine the form URL based on whether it's a create or update operation."""
        pk = self.kwargs.get("component_id") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "horilla_dashboard:move_to_another_dashboard",
                kwargs={"component_id": pk},
            )
        return None

    def get(self, request, *args, **kwargs):
        component_id = self.kwargs.get("component_id")
        if request.user.has_perm(
            "horilla_dashboard.change_dashboard"
        ) or request.user.has_perm("horilla_dashboard.add_dashboard"):
            return super().get(request, *args, **kwargs)

        if component_id:
            dashboard = get_object_or_404(Dashboard, pk=component_id)
            if dashboard.dashboard_owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "error/403.html")

    def form_valid(self, form):
        target_dashboard = form.cleaned_data["dashboard"]
        component_id = self.kwargs.get("component_id")

        try:
            original = DashboardComponent.objects.get(pk=component_id)
        except DashboardComponent.DoesNotExist:
            messages.error(self.request, _("Original component not found."))
            return HttpResponse(status=404)

        with transaction.atomic():
            field_names = [
                f.name
                for f in DashboardComponent._meta.fields
                if f.name not in ["id", "pk", "dashboard"]
            ]
            new_component = DashboardComponent(dashboard=target_dashboard)
            for field in field_names:
                setattr(new_component, field, getattr(original, field))

            new_component.save()

            for crit in original.conditions.all():
                crit.pk = None
                crit.component = new_component
                crit.save()

        messages.success(
            self.request, _("Chart successfully added to another dashboard!")
        )
        return HttpResponse("<script>closeModal();$('#reloadButton').click();</script>")


@method_decorator(htmx_required, name="dispatch")
class DashboardCreateFormView(LoginRequiredMixin, HorillaSingleFormView):
    """View to handle creation and updating of horilla_dashboard."""

    model = Dashboard
    form_class = DashboardForm
    modal_height = False
    fields = ["name", "description", "folder", "is_default", "dashboard_owner"]
    full_width_fields = ["name", "description", "folder", "dashboard_owner"]
    hidden_fields = ["dashboard_owner"]
    save_and_new = False

    @cached_property
    def form_url(self):
        """Determine the form URL based on whether it's a create or update operation."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("horilla_dashboard:dashboard_update", kwargs={"pk": pk})
        return reverse_lazy("horilla_dashboard:dashboard_create")

    def get_initial(self):
        """Set initial company and dashboard_owner; merge GET params into initial."""
        initial = super().get_initial()

        company = (
            getattr(_thread_local, "request", None).active_company
            if hasattr(_thread_local, "request")
            else self.request.user.company
        )
        initial["company"] = company
        initial["dashboard_owner"] = self.request.user

        initial.update(self.request.GET.dict())
        return initial


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_dashboard.delete_dashboard", modal=True),
    name="dispatch",
)
class DashboardDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View to handle deletion of horilla_dashboard."""

    model = Dashboard

    def get_post_delete_response(self):
        """Return HTMX trigger script to reload after delete."""
        return HttpResponse("<script>htmx.trigger('#reloadButton','click');</script>")


# folder areas
@method_decorator(htmx_required, name="dispatch")
class DashboardFolderCreate(LoginRequiredMixin, HorillaSingleFormView):
    """View to handle creation and updating of dashboard folders."""

    model = DashboardFolder
    fields = ["name", "folder_owner", "description", "parent_folder"]
    modal_height = False
    full_width_fields = ["name", "folder_owner", "description", "parent_folder"]
    hidden_fields = ["parent_folder", "folder_owner"]
    save_and_new = False

    def get_form(self, form_class=None):
        """In edit mode (pk set), show only the name field."""
        form = super().get_form(form_class)
        if self.kwargs.get("pk"):
            form.fields = {k: v for k, v in form.fields.items() if k in ["name"]}
        return form

    def get_initial(self):
        """Set parent_folder from GET and folder_owner to current user."""
        initial = super().get_initial()
        pk = self.request.GET.get("pk")
        initial["parent_folder"] = pk if pk else None
        initial["folder_owner"] = self.request.user
        return initial

    @cached_property
    def form_url(self):
        """Determine the form URL based on whether it's a create or update operation."""
        pk = self.kwargs.get("pk")
        if pk:
            return reverse_lazy(
                "horilla_dashboard:dashboard_folder_update", kwargs={"pk": pk}
            )
        return reverse_lazy("horilla_dashboard:dashboard_folder_create")


@method_decorator(htmx_required, name="dispatch")
class DashboardFolderFavoriteView(LoginRequiredMixin, View):
    """View to handle adding/removing a dashboard folder to/from user's favorites."""

    def post(self, request, *args, **kwargs):
        """Handle POST requests to toggle favorite status of a dashboard folder."""
        try:
            folder = DashboardFolder.objects.get(pk=kwargs["pk"])
        except Exception as e:
            messages.error(request, str(e))
            return HttpResponse("<script>$('#reloadButton').click();</script>")

        user = request.user
        if (
            user.has_perm("horilla_dashboard.change_dashboardfolder")
            or folder.folder_owner == user
        ):
            if user in folder.favourited_by.all():
                folder.favourited_by.remove(user)
            else:
                folder.favourited_by.add(user)
        return HttpResponse("<script>$('#reloadButton').click();</script>")

    def get(self, request, *args, **kwargs):
        """Handle GET requests by returning a 403 error page."""
        return render(request, "error/403.html")


@method_decorator(
    permission_required_or_denied(
        [
            "horilla_dashboard.view_dashboardfolder",
            "horilla_dashboard.view_own_dashboardfolder",
        ]
    ),
    name="dispatch",
)
class DashboardFolderListView(LoginRequiredMixin, HorillaListView):
    """View to display the list of dashboard folders."""

    template_name = "dashboard_folder_detail.html"
    model = DashboardFolder
    view_id = "dashboard-folder-list-view"
    search_url = reverse_lazy("horilla_dashboard:dashboard_folder_list_view")
    main_url = reverse_lazy("horilla_dashboard:dashboard_folder_list_view")
    table_width = False
    bulk_select_option = False
    sorting_target = f"#tableview-{view_id}"

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(parent_folder=None)
        return queryset

    columns = ["name", "description"]

    @cached_property
    def action_method(self):
        """Determine the action method based on user permissions."""
        action_method = ""
        if (
            self.request.user.has_perm("horilla_dashboard.change_dashboardfolder")
            or self.request.user.has_perm("horilla_dashboard.delete_dashboardfolder")
            or self.request.user.has_perm("horilla_dashboard.view_own_dashboardfolder")
        ):
            action_method = "actions"

        return action_method

    @cached_property
    def col_attrs(self):
        """Define attributes for the 'name' column to make it clickable if the user has view permissions."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {}
        if self.request.user.has_perm(
            "horilla_dashboard.view_dashboardfolder"
        ) or self.request.user.has_perm("horilla_dashboard.view_own_dashboardfolder"):
            attrs = {
                "hx-get": f"{{get_detail_view_url}}?{query_string}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select": "#mainContent",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Folders"
        for folder in context["object_list"]:
            folder.get_detail_view_url = reverse_lazy(
                "horilla_dashboard:dashboard_folder_detail_list",
                kwargs={"pk": folder.pk},
            )

        return context


@method_decorator(
    permission_required_or_denied(
        ["horilla_dashboard.view_dashboard", "horilla_dashboard.view_own_dashboard"]
    ),
    name="dispatch",
)
class FolderDetailListView(LoginRequiredMixin, HorillaListView):
    """View to display the contents of a specific dashboard folder."""

    template_name = "dashboard_folder_detail.html"
    model = DashboardFolder
    view_id = "dashboard-folder-detail-view"
    table_width = False
    bulk_select_option = False
    sorting_target = f"#tableview-{view_id}"

    columns = [
        (_("Name"), "name"),
        (_("Type"), "get_item_type"),
    ]

    @cached_property
    def action_method(self):
        """Determine the action method based on user permissions."""
        action_method = ""
        if (
            self.request.user.has_perm("horilla_dashboard.change_dashboardfolder")
            or self.request.user.has_perm("horilla_dashboard.delete_dashboardfolder")
            or self.request.user.has_perm("horilla_dashboard.change_dashboard")
            or self.request.user.has_perm("horilla_dashboard.delete_dashboard")
        ):
            action_method = "actions_detail"

        return action_method

    def get(self, request, *args, **kwargs):
        if not self.model.objects.filter(
            folder_owner_id=self.request.user, pk=self.kwargs["pk"]
        ).first() and not self.request.user.has_perm(
            "horilla_dashboard.view_dashboard"
        ):
            return render(self.request, "error/403.html")
        try:
            DashboardFolder.objects.get(pk=self.kwargs["pk"])
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                messages.error(self.request, e)
                return HorillaRefreshResponse(request)
            raise HorillaHttp404(e)
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        folder_id = self.kwargs.get("pk")
        return DashboardFolder.objects.filter(parent_folder__id=folder_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        folder_id = self.kwargs.get("pk")

        folders = DashboardFolder.objects.filter(parent_folder__id=folder_id)
        horilla_dashboard = Dashboard.objects.filter(folder__id=folder_id)

        folders_list = list(folders)
        dashboards_list = list(horilla_dashboard)

        for folder in folders_list:
            folder.item_type = "Folder"
            folder.get_item_type = "Folder"
            folder.hx_target = "#mainContent"
            folder.hx_swap = "outerHTML"
            folder.hx_select = "#mainContent"
            folder.get_detail_view_url = reverse_lazy(
                "horilla_dashboard:dashboard_folder_detail_list",
                kwargs={"pk": folder.pk},
            )

        for dashboard in dashboards_list:
            dashboard.item_type = "Dashboard"
            dashboard.get_item_type = "Dashboard"
            dashboard.hx_target = "#mainContent"
            dashboard.hx_swap = "outerHTML"
            dashboard.hx_select = "#mainContent"
            dashboard.get_detail_view_url = reverse_lazy(
                "horilla_dashboard:dashboard_detail_view", kwargs={"pk": dashboard.pk}
            )

        combined = folders_list + dashboards_list
        combined.sort(key=lambda x: x.name.lower())

        context["object_list"] = combined
        context["queryset"] = combined

        context["total_records_count"] = len(combined)

        title = DashboardFolder.objects.filter(id=folder_id).first()
        context["title"] = title.name if title else "All Folders"
        context["pk"] = folder_id

        query_params = QueryDict(mutable=True)
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)

        context["col_attrs"] = {
            "name": {
                "hx-get": f"{{get_detail_view_url}}?{query_string}",
                "hx-target": "{hx_target}",
                "hx-swap": "{hx_swap}",
                "hx-push-url": "true",
                "hx-select": "{hx_select}",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            },
            "get_item_type": {},
        }

        breadcrumbs = []
        current_folder = DashboardFolder.objects.filter(id=folder_id).first()

        breadcrumbs.append(
            {
                "name": "All Folders",
                "url": f"{reverse_lazy('horilla_dashboard:dashboard_folder_list_view')}?{query_string}",
            }
        )

        folder_chain = []
        temp_folder = current_folder
        while temp_folder:
            folder_chain.append(temp_folder)
            temp_folder = temp_folder.parent_folder

        folder_chain.reverse()

        for folder in folder_chain:
            breadcrumbs.append(
                {
                    "name": folder.name,
                    "url": f"{reverse_lazy('horilla_dashboard:dashboard_folder_detail_list', kwargs={'pk': folder.id})}?{query_string}",
                    "active": folder.id == int(folder_id),
                }
            )

        context["breadcrumbs"] = breadcrumbs

        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        "horilla_dashboard.delete_dashboardfolder", modal=True
    ),
    name="dispatch",
)
class FolderDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View to delete a dashboard folder."""

    model = DashboardFolder

    def get_post_delete_response(self):
        return HttpResponse("<script>htmx.trigger('#reloadButton','click');</script>")


@method_decorator(htmx_required, name="dispatch")
class MoveDashboardView(LoginRequiredMixin, HorillaSingleFormView):
    """View to move a dashboard into a folder."""

    model = Dashboard
    fields = ["folder"]
    modal_height = False
    full_width_fields = ["folder"]

    @cached_property
    def form_url(self):
        """Get the URL for the form, using the dashboard's primary key."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "horilla_dashboard:move_dashboard_to_folder", kwargs={"pk": pk}
            )
        return None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def get(self, request, *args, **kwargs):
        dashboard_id = self.kwargs.get("pk")
        if request.user.has_perm(
            "horilla_dashboard.change_dashboard"
        ) or request.user.has_perm("horilla_dashboard.add_dashboard"):
            return super().get(request, *args, **kwargs)

        if dashboard_id:
            dashboard = get_object_or_404(Dashboard, pk=dashboard_id)
            if dashboard.dashboard_owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "error/403.html")

    def get_form(self, form_class=None):
        """Add widget attrs and restrict folder queryset for non-superusers."""
        form = super().get_form(form_class)
        user = getattr(self.request, "user", None)
        if user:
            form.fields["folder"].widget.attrs.update(
                {
                    "class": "js-example-basic-single",
                }
            )
            if not user.is_superuser:
                form.fields["folder"].queryset = DashboardFolder.objects.filter(
                    folder_owner=user
                )
        return form


@method_decorator(htmx_required, name="dispatch")
class MoveFolderView(LoginRequiredMixin, HorillaSingleFormView):
    """View to move a dashboard folder into another folder."""

    model = DashboardFolder
    fields = ["parent_folder"]
    modal_height = False
    full_width_fields = ["parent_folder"]

    @cached_property
    def form_url(self):
        """Get the URL for the form, using the folder's primary key."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "horilla_dashboard:move_folder_to_folder", kwargs={"pk": pk}
            )
        return None

    def get(self, request, *args, **kwargs):
        folder_id = self.kwargs.get("pk")
        if request.user.has_perm(
            "horilla_dashboard.change_dashboard"
        ) or request.user.has_perm("horilla_dashboard.add_dashboard"):
            return super().get(request, *args, **kwargs)

        if folder_id:
            folder = get_object_or_404(DashboardFolder, pk=folder_id)
            if folder.folder_owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "error/403.html")

    def get_form(self, form_class=None):
        """Add widget attrs and restrict parent_folder queryset for non-superusers."""
        form = super().get_form(form_class)
        user = getattr(self.request, "user", None)
        if user:
            form.fields["parent_folder"].widget.attrs.update(
                {
                    "class": "js-example-basic-single",
                }
            )
            if not user.is_superuser:
                form.fields["parent_folder"].queryset = DashboardFolder.objects.filter(
                    folder_owner=user
                )
        return form


# favourite area


@method_decorator(
    permission_required_or_denied(
        ["horilla_dashboard.view_dashboard", "horilla_dashboard.view_own_dashboard"]
    ),
    name="dispatch",
)
class FavouriteDashboardListView(LoginRequiredMixin, HorillaListView):
    """List view for favourite horilla_dashboard."""

    model = Dashboard
    template_name = "favourite_dashboard.html"
    view_id = "favourite-dashboard-list"
    filterset_class = DashboardFilter
    search_url = reverse_lazy("horilla_dashboard:dashboard_favourite_list_view")
    main_url = reverse_lazy("horilla_dashboard:dashboard_favourite_list_view")
    table_width = False
    bulk_select_option = False
    sorting_target = f"#tableview-{view_id}"

    @cached_property
    def action_method(self):
        """Determine if action buttons should be displayed based on user permissions."""
        action_method = ""
        if self.request.user.has_perm(
            "horilla_dashboard.change_dashboard"
        ) or self.request.user.has_perm("horilla_dashboard.delete_dashboard"):
            action_method = "actions"

        return action_method

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = _("Favourite Dashboards")
        return context

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(favourited_by=self.request.user)
        return queryset

    columns = ["name", "description", "folder"]

    @cached_property
    def col_attrs(self):
        """Define attributes for columns, including HTMX attributes for interactivity."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {}
        if self.request.user.has_perm("horilla_dashboard.view_dashboard"):
            attrs = {
                "hx-get": f"{{get_detail_view_url}}?{query_string}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select": "#mainContent",
            }
        return [
            {
                "name": {
                    "style": "cursor:pointer",
                    "class": "hover:text-primary-600",
                    **attrs,
                }
            }
        ]


@method_decorator(
    permission_required_or_denied(
        [
            "horilla_dashboard.view_dashboardfolder",
            "horilla_dashboard.view_own_dashboardfolder",
        ]
    ),
    name="dispatch",
)
class FavouriteFolderListView(HorillaListView):
    """List view for favourite dashboard folders."""

    template_name = "favourite_folder.html"
    model = DashboardFolder
    table_width = False
    view_id = "favourite-folder-list-view"
    bulk_select_option = False
    sorting_target = f"#tableview-{view_id}"

    @cached_property
    def action_method(self):
        """Determine if action buttons should be displayed based on user permissions."""
        action_method = ""
        if (
            self.request.user.has_perm("horilla_dashboard.change_dashboardfolder")
            or self.request.user.has_perm("horilla_dashboard.delete_dashboardfolder")
            or self.request.user.has_perm("horilla_dashboard.change_dashboard")
            or self.request.user.has_perm("horilla_dashboard.delete_dashboard")
        ):
            action_method = "actions"

        return action_method

    columns = ["name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        queryset = queryset.filter(parent_folder=None, favourited_by=self.request.user)
        return queryset

    @cached_property
    def col_attrs(self):
        """Define attributes for columns, including HTMX attributes for interactivity."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {}
        if self.request.user.has_perm("horilla_dashboard.view_dashboardfolder"):
            attrs = {
                "hx-get": f"{{get_detail_view_url}}?{query_string}",
                "hx-target": "#mainContent",
                "hx-swap": "outerHTML",
                "hx-select": "#mainContent",
                "hx-push-url": "true",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Favourite Folders"
        return context


@method_decorator(
    permission_required_or_denied("horilla_dashboard.change_dashboard"), name="dispatch"
)
class ReorderComponentsView(LoginRequiredMixin, View):
    """
    Handle the final save of component reordering (both regular components and KPIs)
    """

    def post(self, request, *args, **kwargs):
        """Reorder components based on the provided order in the POST data."""
        dashboard_id = kwargs.get("dashboard_id")

        try:
            dashboard = get_object_or_404(Dashboard, id=dashboard_id)

            component_order = request.POST.getlist("component_order")
            reorder_type = request.POST.get("reorder_type", "components")

            if not component_order:
                messages.error(
                    self.request,
                    _("No component order provided. Please try reordering again."),
                )
                return JsonResponse(
                    {
                        "success": False,
                        "message": str(_("No component order provided.")),
                    }
                )

            if reorder_type == "kpi":
                valid_components = DashboardComponent.objects.filter(
                    dashboard=dashboard, id__in=component_order, component_type="kpi"
                )
            else:
                valid_components = DashboardComponent.objects.filter(
                    dashboard=dashboard,
                    id__in=component_order,
                    component_type__in=["chart", "table_data"],  # All non-KPI types
                )

            valid_component_ids = list(valid_components.values_list("id", flat=True))

            valid_component_ids = [str(id) for id in valid_component_ids]

            invalid_ids = set(component_order) - set(valid_component_ids)
            if invalid_ids:
                messages.error(
                    self.request,
                    _("Invalid component order. Please refresh and try again."),
                )
                return JsonResponse(
                    {"success": False, "message": str(_("Invalid component order."))}
                )

            # Save per-user layout order in the same model as default home
            with transaction.atomic():
                layout_order, created = DefaultHomeLayoutOrder.objects.get_or_create(
                    user=request.user,
                    dashboard=dashboard,
                    defaults={"order": {"kpi": [], "components": []}},
                )
                order_dict = (
                    layout_order.order if isinstance(layout_order.order, dict) else {}
                )
                order_dict = dict(order_dict)
                if reorder_type == "kpi":
                    order_dict["kpi"] = [int(x) for x in component_order]
                else:
                    order_dict["components"] = [int(x) for x in component_order]
                layout_order.order = order_dict
                layout_order.save(update_fields=["order"])

            messages.success(request, _("Components reordered successfully!"))

            return JsonResponse({"success": True})

        except Exception as e:
            messages.error(self.request, e)
            return JsonResponse({"success": False, "message": str(e)})


def _get_default_home_previous_order(user):
    """Return the user's last saved default home layout order, or None if none saved."""
    layout = DefaultHomeLayoutOrder.objects.filter(
        user=user, dashboard__isnull=True
    ).first()
    if layout and isinstance(layout.order, dict):
        return layout.order
    return None


def _get_valid_default_home_layout_ids(user, date_range=None):
    """Return (valid_kpi_ids, valid_block_ids) from generator counts only."""
    user_company = getattr(user, "company", None)
    generator = DefaultDashboardGenerator(user, user_company, date_range=date_range)
    n_kpi = len(generator.generate_kpi_data())
    n_chart = len(generator.generate_chart_data())
    n_table = len(generator.generate_table_data())
    valid_kpi_ids = {f"default-kpi-{i}" for i in range(n_kpi)}
    valid_block_ids = {f"default-chart-{i}" for i in range(n_chart)} | {
        f"default-table-{i}" for i in range(n_table)
    }
    return valid_kpi_ids, valid_block_ids


class SaveDefaultHomeLayoutOrderView(LoginRequiredMixin, View):
    """Save default home page layout order (KPIs, charts, tables) for the current user."""

    def _error_response(self, request, message, previous_order):
        messages.error(request, message)
        return JsonResponse(
            {
                "success": False,
                "message": message,
                "order": previous_order,
            }
        )

    def post(self, request, *args, **kwargs):
        """Validate and save default home KPI/charts order; return JSON success or error."""
        previous_order = _get_default_home_previous_order(request.user)

        try:
            # ---- Parse request body ----
            if request.content_type and "application/json" in request.content_type:
                body = json.loads(request.body or "{}")
            else:
                body = request.POST.dict()

            order_data = body.get("order")
            if not isinstance(order_data, dict):
                order_data = {}

            # ---- Required keys validation ----
            if "kpi" not in order_data:
                return self._error_response(
                    request, _("KPI data is missing in the request"), previous_order
                )

            if "chartsAndTables" not in order_data:
                return self._error_response(
                    request,
                    _("Charts and tables data is missing in the request"),
                    previous_order,
                )

            kpi = order_data.get("kpi")
            charts_and_tables = order_data.get("chartsAndTables")

            # ---- Type validation ----
            if not isinstance(kpi, list):
                return self._error_response(
                    request,
                    _("KPI data is invalid. Expected a list"),
                    previous_order,
                )

            if not isinstance(charts_and_tables, list):
                return self._error_response(
                    request,
                    _("Charts and tables data is invalid. Expected a list"),
                    previous_order,
                )

            # ---- Empty validation ----
            if not kpi:
                return self._error_response(
                    request, _("KPI order is empty."), previous_order
                )

            if not charts_and_tables:
                return self._error_response(
                    request,
                    _("Charts and tables order cannot be empty."),
                    previous_order,
                )

            kpi_pattern = re.compile(r"^default-kpi-\d+$")
            if not all(isinstance(i, str) and kpi_pattern.match(i) for i in kpi):
                return self._error_response(
                    request, _("Invalid KPI id in order."), previous_order
                )

            block_pattern = re.compile(r"^default-(?:chart|table)-\d+$")
            if not all(
                isinstance(i, str) and block_pattern.match(i) for i in charts_and_tables
            ):
                return self._error_response(
                    request,
                    _("Invalid chart or table id in order."),
                    previous_order,
                )

            date_range = body.get("date_range") or request.GET.get("date_range")
            if date_range == "all":
                date_range = None
            valid_kpi_ids, valid_block_ids = _get_valid_default_home_layout_ids(
                request.user, date_range=date_range
            )
            kpi_set = set(kpi)
            if kpi_set != valid_kpi_ids or len(kpi) != len(valid_kpi_ids):
                return self._error_response(
                    request,
                    _(
                        "Invalid KPI order: IDs must match the current default home KPIs."
                    ),
                    previous_order,
                )
            charts_tables_set = set(charts_and_tables)
            if charts_tables_set != valid_block_ids or len(charts_and_tables) != len(
                valid_block_ids
            ):
                return self._error_response(
                    request,
                    _(
                        "Invalid charts/tables order: IDs must match the current default home charts and tables."
                    ),
                    previous_order,
                )

            order = {
                "kpi": kpi,
                "chartsAndTables": charts_and_tables,
            }

            DefaultHomeLayoutOrder.objects.update_or_create(
                user=request.user,
                dashboard=None,
                defaults={"order": order},
            )

            messages.success(request, _("Layout order saved successfully"))
            return JsonResponse({"success": True, "message": _("Layout order saved.")})

        except Exception as e:
            messages.error(request, e)
            return JsonResponse(
                {"success": False, "message": str(e), "order": previous_order}
            )


class ResetDefaultHomeLayoutOrderView(LoginRequiredMixin, View):
    """Remove the current user's saved default home layout order and revert to template default."""

    def post(self, request, *args, **kwargs):
        """Delete user's default home layout order and return JSON response."""
        try:
            DefaultHomeLayoutOrder.objects.filter(
                user=request.user, dashboard__isnull=True
            ).delete()
            messages.success(self.request, _("Layout reset to default."))
            return JsonResponse(
                {"success": True, "message": _("Layout reset to default.")}
            )
        except Exception as e:
            messages.error(self.request, e)
            return JsonResponse({"success": False, "message": str(e)})


@method_decorator(
    permission_required_or_denied("horilla_dashboard.change_dashboard"), name="dispatch"
)
class ResetDashboardLayoutOrderView(LoginRequiredMixin, View):
    """Remove the current user's saved layout order for this dashboard so default order is used."""

    def post(self, request, *args, **kwargs):
        """Delete user's layout order for the given dashboard and return JSON response."""
        dashboard_id = kwargs.get("dashboard_id")
        try:
            dashboard = get_object_or_404(Dashboard, id=dashboard_id)
            DefaultHomeLayoutOrder.objects.filter(
                user=request.user, dashboard=dashboard
            ).delete()
            messages.success(request, _("Dashboard layout reset to default order."))
            return JsonResponse(
                {"success": True, "message": _("Dashboard layout reset to default.")}
            )
        except Exception as e:
            messages.error(self.request, e)
            return JsonResponse({"success": False, "message": str(e)})


@method_decorator(htmx_required, name="dispatch")
class ReportToDashboardForm(LoginRequiredMixin, HorillaSingleFormView):
    """
    View to handle adding a report into a dashboard.
    """

    model = DashboardComponent
    modal_height = False
    form_title = _("Add to Dashboard")
    fields = ["dashboard", "reports"]
    full_width_fields = ["dashboard", "reports"]
    save_and_new = False

    def get_form_kwargs(self):
        """
        Pass the request to the form for queryset filtering and validation.
        """
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def get_initial(self):
        """Set initial reports from report_id in GET when adding report to dashboard."""
        initial = super().get_initial()
        report_id = self.request.GET.get("report_id")
        if report_id:
            initial["reports"] = report_id
        return initial

    def get(self, request, *args, **kwargs):
        """Check change_dashboard/add_dashboard or dashboard ownership; then show form or 403."""
        component_id = self.kwargs.get("component_id")
        if request.user.has_perm(
            "horilla_dashboard.change_dashboard"
        ) or request.user.has_perm("horilla_dashboard.add_dashboard"):
            return super().get(request, *args, **kwargs)

        if component_id:
            dashboard = get_object_or_404(Dashboard, pk=component_id)
            if dashboard.dashboard_owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "error/403.html")

    def get_form(self, form_class=None):
        """Add widget attrs and restrict dashboard queryset for non-superusers."""
        form = super().get_form(form_class)
        user = getattr(self.request, "user", None)
        if user:
            form.fields["dashboard"].widget.attrs.update(
                {
                    "class": "js-example-basic-single",
                }
            )
            if not user.is_superuser:
                form.fields["dashboard"].queryset = Dashboard.objects.filter(
                    dashboard_owner=user
                )
        return form

    @cached_property
    def form_url(self):
        """Determine the form URL based on whether it's a create or update operation."""
        return reverse_lazy("horilla_dashboard:report_to_dashboard")

    def form_valid(self, form):
        """
        Create a new DashboardComponent entry using the report.
        """
        selected_dashboard = form.cleaned_data["dashboard"]
        report_id = self.request.GET.get("report_id")

        try:
            report = Report.objects.get(pk=report_id)

            existing_component = DashboardComponent.objects.filter(
                dashboard=selected_dashboard, reports=report, is_active=True
            ).first()

            if existing_component:
                messages.warning(
                    self.request,
                    _(
                        "This report '{}' is already added to the '{}' dashboard."
                    ).format(report.name, selected_dashboard.name),
                )
                return HttpResponse(
                    "<script>$('#reloadButton').click();closeModal();</script>"
                )

            DashboardComponent.objects.create(
                dashboard=selected_dashboard,
                name=report.name,
                component_type="chart",
                chart_type=report.chart_type,
                reports=report,
                module=report.module,
                grouping_field=report.chart_field,
                secondary_grouping=report.chart_field_stacked,
                component_owner=self.request.user,
                company=self.request.user.company,
            )

            messages.success(self.request, _("Report added to dashboard successfully!"))
            return HttpResponse(
                "<script>$('#reloadButton').click();closeModal();</script>"
            )

        except Report.DoesNotExist:
            messages.error(self.request, _("Report not found."))
            return HttpResponse(
                "<script>$('#reloadButton').click();closeModal();</script>"
            )
