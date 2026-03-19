"""

Django class-based views for managing and displaying sales forecast data in Horilla CRM.
Features: Period-based forecasts, trend analysis, user/aggregated views, optimized queries.
"""

# Third-party imports (Django)
from django.contrib.auth.mixins import LoginRequiredMixin

from horilla.auth.models import User

# First-party / Horilla imports
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla_core.models import FiscalYearInstance
from horilla_core.services.fiscal_year_service import FiscalYearService
from horilla_crm.forecast.models import ForecastType
from horilla_generics.views import HorillaTabView, HorillaView


class ForecastView(LoginRequiredMixin, HorillaView):
    """Main forecast dashboard view with fiscal year and user filtering capabilities."""

    template_name = "forecast_view.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        forcast_types = ForecastType.objects.all()
        type_count = forcast_types.count()
        fiscal_years = FiscalYearInstance.objects.all()
        current_instance = fiscal_years.filter(is_current=True).first()

        fiscal_year_id = self.request.GET.get("fiscal_year_id")
        user_id = self.request.GET.get("user_id")

        selected_instance = (
            FiscalYearInstance.objects.get(id=fiscal_year_id)
            if fiscal_year_id
            and FiscalYearInstance.objects.filter(id=fiscal_year_id).exists()
            else current_instance
        )

        query_params = self.request.GET.copy()
        query_string = query_params.urlencode() if query_params else ""

        context.update(
            {
                "users": User.objects.filter(is_active=True),
                "fiscal_years": fiscal_years,
                "current_instance": current_instance,
                "selected_instance": selected_instance,
                "previous_instance": None,
                "next_instance": None,
                "user_id": user_id,
                "fiscal_year_id": fiscal_year_id,
                "query_string": query_string,
                "type_count": type_count,
            }
        )

        if fiscal_years and selected_instance:
            instances_list = list(fiscal_years)
            try:
                current_index = instances_list.index(selected_instance)
                if current_index > 0:
                    context["previous_instance"] = instances_list[current_index - 1]
                if current_index < len(instances_list) - 1:
                    context["next_instance"] = instances_list[current_index + 1]
            except ValueError:
                pass

        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class ForecastNavbarView(LoginRequiredMixin, HorillaView):
    """Dynamically load forecast navbar/filters."""

    template_name = "forecast_navbar.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Automatically check and update fiscal years before displaying
        company = (
            self.request.active_company
            if hasattr(self.request, "active_company") and self.request.active_company
            else (
                self.request.user.company
                if hasattr(self.request.user, "company")
                else None
            )
        )
        if company:
            FiscalYearService.check_and_update_fiscal_years(company=company)

        forcast_types = ForecastType.objects.all()
        type_count = forcast_types.count()
        fiscal_years = FiscalYearInstance.objects.all()
        current_instance = fiscal_years.filter(is_current=True).first()

        fiscal_year_id = self.request.GET.get("fiscal_year_id")
        user_id = self.request.GET.get("user_id")

        selected_instance = (
            FiscalYearInstance.objects.get(id=fiscal_year_id)
            if fiscal_year_id
            and FiscalYearInstance.objects.filter(id=fiscal_year_id).exists()
            else current_instance
        )

        query_params = self.request.GET.copy()
        query_string = query_params.urlencode() if query_params else ""

        # Check permissions
        has_view_all = self.request.user.has_perm("opportunities.view_opportunity")
        has_view_own = self.request.user.has_perm("opportunities.view_own_opportunity")

        # Determine user list and default selection based on permissions
        if has_view_all:
            # User can view all opportunities - show all users
            users = User.objects.filter(is_active=True)
            show_all_users_option = True
            # If no user_id is specified, don't force one (show all by default)
            if not user_id:
                user_id = None
        elif has_view_own:
            # User can only view their own opportunities - restrict to current user only
            users = User.objects.filter(id=self.request.user.id, is_active=True)
            show_all_users_option = False
            # Force user_id to be the current user
            user_id = str(self.request.user.pk)
        else:
            # No permission - empty queryset
            users = User.objects.none()
            show_all_users_option = False
            user_id = None

        context.update(
            {
                "users": users,
                "fiscal_years": fiscal_years,
                "current_instance": current_instance,
                "selected_instance": selected_instance,
                "user_id": user_id,
                "fiscal_year_id": fiscal_year_id,
                "query_string": query_string,
                "type_count": type_count,
                "show_all_users_option": show_all_users_option,
                "has_view_all": has_view_all,
                "has_view_own": has_view_own,
            }
        )

        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class ForecastTabView(LoginRequiredMixin, HorillaTabView):
    """Tabbed interface view for organizing different forecast types within a company."""

    view_id = "forecast-tab-view"
    background_class = "rounded-md"
    tab_class = "h-[calc(_100vh_-_300px_)] overflow-x-auto custom-scroll"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tabs = self.get_forecast_tabs()

    def get_forecast_tabs(self):
        """Generate tab configuration for each active forecast type with URLs and IDs."""
        tabs = []
        company = None
        if self.request.user.is_authenticated:
            company = (
                self.request.active_company
                if self.request.active_company
                else self.request.user.company
            )
        forecast_types = ForecastType.objects.filter(
            is_active=True, company=company
        ).order_by("created_at")

        query_params = self.request.GET.copy()
        for index, forecast_type in enumerate(forecast_types, 1):
            url = reverse_lazy(
                "forecast:forecast_type_tab_view", kwargs={"pk": forecast_type.id}
            )
            if query_params:
                url = f"{url}?{query_params.urlencode()}"
            tab = {
                "title": forecast_type.name or f"Forecast {index}",
                "url": url,
                "target": f"forecast-{forecast_type.id}-content",
                "id": f"forecast-{forecast_type.id}-view",
            }
            tabs.append(tab)
        return tabs
