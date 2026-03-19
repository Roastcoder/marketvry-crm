"""Forecast type tab view (period-by-period data, trends, targets)."""

# Third-party imports (Django)
from django.contrib import messages
from django.views.generic import TemplateView

# First-party / Horilla imports
from horilla.http import HttpResponse
from horilla.shortcuts import get_object_or_404, render
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla_core.models import FiscalYearInstance
from horilla_core.services.fiscal_year_service import FiscalYearService
from horilla_crm.forecast.models import ForecastType
from horilla_crm.forecast.views.core.helpers import ForecastTypeTabHelpersMixin
from horilla_crm.forecast.views.core.mixins import ForecastTypeTabMixin


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class ForecastTypeTabView(
    ForecastTypeTabMixin, ForecastTypeTabHelpersMixin, TemplateView
):
    """
    Detailed forecast view displaying period-by-period data with trends, targets,
    and performance metrics for a specific forecast type.
    """

    template_name = "forecast_type_view.html"
    USERS_PER_PAGE = 10

    def get(self, request, *args, **kwargs):
        user_id = request.GET.get("user_id")
        has_view_all = request.user.has_perm("opportunities.view_opportunity")
        has_view_own = request.user.has_perm("opportunities.view_own_opportunity")

        if has_view_own and not has_view_all:
            if user_id and user_id != str(request.user.pk):
                return render(request, "403.html")
            if not user_id:
                request.GET = request.GET.copy()
                request.GET["user_id"] = str(request.user.pk)

        context = self.get_context_data(**kwargs)
        if context.get("error"):
            return HttpResponse("<script>$('#reloadButton').click();</script>")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        forecast_type_id = kwargs.get("pk")
        try:
            forecast_type = get_object_or_404(
                ForecastType, id=forecast_type_id, is_active=True
            )
        except Exception as e:
            messages.error(self.request, str(e))
            context["error"] = True
            return context

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

        fiscal_year_id = self.request.GET.get("fiscal_year_id")
        fiscal_year = (
            FiscalYearInstance.objects.get(id=fiscal_year_id)
            if fiscal_year_id
            and FiscalYearInstance.objects.filter(id=fiscal_year_id).exists()
            else self.get_current_fiscal_year
        )

        self.ensure_forecasts_exist(forecast_type, fiscal_year)

        # Get user_id - this will be current user if they only have view_own permission
        user_id = self.request.GET.get("user_id")

        # Additional permission check
        has_view_all = self.request.user.has_perm("opportunities.view_opportunity")
        has_view_own = self.request.user.has_perm("opportunities.view_own_opportunity")

        # If user only has view_own, ensure they can only see their own data
        if has_view_own and not has_view_all:
            if not user_id or user_id != str(self.request.user.pk):
                user_id = str(self.request.user.pk)

        page = self.request.GET.get("page", 1)
        forecasts = self.get_forecast_data(forecast_type, fiscal_year, user_id, page)

        # Calculate totals for all periods
        forecast_totals = self.calculate_forecast_totals(forecasts, forecast_type)

        currency_symbol = (
            self.get_company_for_user.currency if self.get_company_for_user else "USD"
        )

        # Construct search_url and search_params for HTMX
        search_url = self.request.path
        search_params = self.request.GET.copy()
        if "page" in search_params:
            del search_params["page"]
        search_params = search_params.urlencode()

        title = (
            f"{forecast_type.get_forecast_type_display} Forecast for {fiscal_year.name}"
        )

        context.update(
            {
                "forecast_type": forecast_type,
                "fiscal_year": fiscal_year,
                "forecasts": forecasts,
                "forecast_totals": forecast_totals,
                "currency_symbol": currency_symbol,
                "user_id": user_id,
                "title": title,
                "search_url": search_url,
                "search_params": search_params,
                "has_view_all": has_view_all,
                "has_view_own": has_view_own,
            }
        )
        return context

    def calculate_forecast_totals(self, forecasts, forecast_type):
        """Calculate totals across all periods for the forecast data."""

        class ForecastTotals:
            """
            Aggregated totals across ALL forecasts (all users, all periods)
            for display in the totals row at the bottom of the table.
            """

            def __init__(self):
                self.forecast_type = forecast_type
                if forecast_type.is_quantity_based:
                    self.target_quantity = 0
                    self.pipeline_quantity = 0
                    self.best_case_quantity = 0
                    self.commit_quantity = 0
                    self.closed_quantity = 0
                    self.actual_quantity = 0
                    self.gap_quantity = 0
                else:
                    self.target_amount = 0
                    self.pipeline_amount = 0
                    self.best_case_amount = 0
                    self.commit_amount = 0
                    self.closed_amount = 0
                    self.actual_amount = 0
                    self.gap_amount = 0

                self.performance_percentage = 0
                self.gap_percentage = 0
                self.closed_percentage = 0
                self.closed_deals_count = 0

        totals = ForecastTotals()

        if not forecasts:
            return totals

        for forecast in forecasts:
            if forecast_type.is_quantity_based:
                totals.target_quantity += getattr(forecast, "target_quantity", 0) or 0
                totals.pipeline_quantity += (
                    getattr(forecast, "pipeline_quantity", 0) or 0
                )
                totals.best_case_quantity += (
                    getattr(forecast, "best_case_quantity", 0) or 0
                )
                totals.commit_quantity += getattr(forecast, "commit_quantity", 0) or 0
                totals.closed_quantity += getattr(forecast, "closed_quantity", 0) or 0
                totals.actual_quantity += getattr(forecast, "actual_quantity", 0) or 0
            else:
                totals.target_amount += getattr(forecast, "target_amount", 0) or 0
                totals.pipeline_amount += getattr(forecast, "pipeline_amount", 0) or 0
                totals.best_case_amount += getattr(forecast, "best_case_amount", 0) or 0
                totals.commit_amount += getattr(forecast, "commit_amount", 0) or 0
                totals.closed_amount += getattr(forecast, "closed_amount", 0) or 0
                totals.actual_amount += getattr(forecast, "actual_amount", 0) or 0

            totals.closed_deals_count += getattr(forecast, "closed_deals_count", 0) or 0

        # Calculate derived metrics
        if forecast_type.is_quantity_based:
            totals.gap_quantity = totals.target_quantity - totals.actual_quantity
            if totals.target_quantity > 0:
                totals.performance_percentage = (
                    totals.actual_quantity / totals.target_quantity
                ) * 100
                totals.gap_percentage = (
                    totals.gap_quantity / totals.target_quantity
                ) * 100
                totals.closed_percentage = (
                    totals.closed_quantity / totals.target_quantity
                ) * 100
        else:
            totals.gap_amount = totals.target_amount - totals.actual_amount
            if totals.target_amount > 0:
                totals.performance_percentage = (
                    totals.actual_amount / totals.target_amount
                ) * 100
                totals.gap_percentage = (totals.gap_amount / totals.target_amount) * 100
                totals.closed_percentage = (
                    totals.closed_amount / totals.target_amount
                ) * 100

        return totals
