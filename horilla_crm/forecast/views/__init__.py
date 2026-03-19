"""Aggregate view modules for the `horilla_crm.forecast.views` package."""

from horilla_crm.forecast.views.core import (
    ForecastView,
    ForecastNavbarView,
    ForecastTabView,
    ForecastTypeTabView,
    ForecastOpportunitiesView,
)

from horilla_crm.forecast.views.forecast_target import (
    ForecastTargetView,
    ForecastTargetFiltersView,
    ForecastTargetNavbar,
    ForecastTargetListView,
    ForecastTargetFormView,
    ToggleRoleBasedView,
    ToggleConditionFieldsView,
    UpdateTargetHelpTextView,
    UpdateForecastTarget,
    ForecastTargetDeleteView,
)

from horilla_crm.forecast.views.forecast_type import (
    ForecastTypeView,
    ForecastTypeNavbar,
    ForecastTypeListView,
    ForecastTypeFormView,
    ForecastTypeDeleteView,
)

__all__ = [
    # core
    "ForecastView",
    "ForecastNavbarView",
    "ForecastTabView",
    "ForecastTypeTabView",
    "ForecastOpportunitiesView",
    # forecast_target
    "ForecastTargetView",
    "ForecastTargetFiltersView",
    "ForecastTargetNavbar",
    "ForecastTargetListView",
    "ForecastTargetFormView",
    "ToggleRoleBasedView",
    "ToggleConditionFieldsView",
    "UpdateTargetHelpTextView",
    "UpdateForecastTarget",
    "ForecastTargetDeleteView",
    # forecast_type
    "ForecastTypeView",
    "ForecastTypeNavbar",
    "ForecastTypeListView",
    "ForecastTypeFormView",
    "ForecastTypeDeleteView",
]
