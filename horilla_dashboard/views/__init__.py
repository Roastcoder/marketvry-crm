"""Views for managing horilla_dashboard, including list and detail views with component rendering."""

from horilla_dashboard.views.core import (
    DashboardNavbar,
    DashboardDetailView,
    DashboardListView,
)

from horilla_dashboard.views.home import (
    HomePageView,
    SaveDefaultHomeLayoutOrderView,
    ResetDefaultHomeLayoutOrderView,
)

from horilla_dashboard.views.component import (
    DashboardComponentTableDataView,
    DashboardComponentFormView,
    ComponentDeleteView,
    AddToDashboardForm,
    ReportToDashboardForm,
    ChartViewToDashboardForm,
    ReorderComponentsView,
)

from horilla_dashboard.views.folder import (
    DashboardFolderCreate,
    DashboardFolderFavoriteView,
    DashboardFolderListView,
    FolderDetailListView,
    FolderDeleteView,
    MoveDashboardView,
    MoveFolderView,
)

from horilla_dashboard.views.field_choices import (
    ModuleFieldChoicesView,
    ColumnFieldChoicesView,
    GroupingFieldChoicesView,
    SecondaryGroupingFieldChoicesView,
)

from horilla_dashboard.views.chart import (
    ChartPreviewView,
    DashboardComponentChartView,
)

from horilla_dashboard.views.dashboard_actions import (
    DashboardDefaultToggleView,
    DashboardFavoriteToggleView,
    DashboardCreateFormView,
    DashboardDeleteView,
    ResetDashboardLayoutOrderView,
)

from horilla_dashboard.views.favourite import (
    FavouriteDashboardListView,
    FavouriteFolderListView,
)

from horilla_dashboard.views.helper import get_queryset_for_module

from horilla_dashboard.views.dashboard_helper import (
    get_kpi_data,
    get_report_chart_data,
    get_chart_data,
    apply_conditions,
    get_table_data,
)

__all__ = [
    # core
    "DashboardNavbar",
    "DashboardDetailView",
    "DashboardListView",
    # home
    "HomePageView",
    "SaveDefaultHomeLayoutOrderView",
    "ResetDefaultHomeLayoutOrderView",
    # components
    "DashboardComponentTableDataView",
    "DashboardComponentFormView",
    "ComponentDeleteView",
    "AddToDashboardForm",
    "ReportToDashboardForm",
    "ChartViewToDashboardForm",
    "ReorderComponentsView",
    # folders
    "DashboardFolderCreate",
    "DashboardFolderFavoriteView",
    "DashboardFolderListView",
    "FolderDetailListView",
    "FolderDeleteView",
    "MoveDashboardView",
    "MoveFolderView",
    # field choices
    "ModuleFieldChoicesView",
    "ColumnFieldChoicesView",
    "GroupingFieldChoicesView",
    "SecondaryGroupingFieldChoicesView",
    # charts
    "ChartPreviewView",
    "DashboardComponentChartView",
    # dashboard actions
    "DashboardDefaultToggleView",
    "DashboardFavoriteToggleView",
    "DashboardCreateFormView",
    "DashboardDeleteView",
    "ResetDashboardLayoutOrderView",
    # favourites
    "FavouriteDashboardListView",
    "FavouriteFolderListView",
    # helpers (public)
    "get_queryset_for_module",
    "get_kpi_data",
    "get_report_chart_data",
    "get_chart_data",
    "apply_conditions",
    "get_table_data",
]
