"""
Forecast Views Module

This package provides forecast dashboard, type tab and opportunities views.
Submodules: dashboard, type_tab, opportunities.
"""

from horilla_crm.forecast.views.core.dashboard import (
    ForecastNavbarView,
    ForecastTabView,
    ForecastView,
)
from horilla_crm.forecast.views.core.opportunities import ForecastOpportunitiesView
from horilla_crm.forecast.views.core.type_tab import ForecastTypeTabView

__all__ = [
    "ForecastView",
    "ForecastNavbarView",
    "ForecastTabView",
    "ForecastTypeTabView",
    "ForecastOpportunitiesView",
]
