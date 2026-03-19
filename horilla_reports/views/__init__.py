"""Aggregate and re-export report-related views for convenience imports."""

from horilla_reports.views.core import (
    ReportNavbar,
    ReportsListView,
    FavouriteReportsListView,
    CreateFolderView,
    ReportFolderListView,
    FavouriteReportFolderListView,
    ReportFolderDetailView,
    MarkFolderAsFavouriteView,
    MarkReportAsFavouriteView,
    ReportDeleteView,
    FolderDeleteView,
    SearchAvailableFieldsView,
)
from horilla_reports.views.default_reports import (
    LoadDefaultReportsModalView,
    CreateSelectedDefaultReportsView,
)
from horilla_reports.views.export_views import ReportExportView
from horilla_reports.views.report_crud import (
    ChangeChartTypeView,
    ChangeChartFieldView,
    CreateReportView,
    UpdateReportView,
    MoveReportView,
    MoveFolderView,
    GetModuleColumnsHTMXView,
    ReportUpdateView,
    DiscardReportChangesView,
    SaveReportChangesView,
    CloseReportPanelView,
)
from horilla_reports.views.report_detail import ReportDetailView
from horilla_reports.views.report_filter_detail import ReportDetailFilteredView
from horilla_reports.views.report_preview import (
    ToggleAggregateView,
    UpdateAggregateFunctionView,
    AddColumnView,
    RemoveColumnView,
    AddFilterFieldView,
    UpdateFilterOperatorView,
    UpdateFilterValueView,
    UpdateFilterLogicView,
    RemoveFilterView,
    ToggleRowGroupView,
    RemoveRowGroupView,
    ToggleColumnGroupView,
    RemoveColumnGroupView,
    RemoveAggregateColumnView,
)

__all__ = [
    # core
    "ReportNavbar",
    "ReportsListView",
    "FavouriteReportsListView",
    "CreateFolderView",
    "ReportFolderListView",
    "FavouriteReportFolderListView",
    "ReportFolderDetailView",
    "MarkFolderAsFavouriteView",
    "MarkReportAsFavouriteView",
    "ReportDeleteView",
    "FolderDeleteView",
    "SearchAvailableFieldsView",
    # default_reports
    "LoadDefaultReportsModalView",
    "CreateSelectedDefaultReportsView",
    # export_views
    "ReportExportView",
    # report_crud
    "ChangeChartTypeView",
    "ChangeChartFieldView",
    "CreateReportView",
    "UpdateReportView",
    "MoveReportView",
    "MoveFolderView",
    "GetModuleColumnsHTMXView",
    "ReportUpdateView",
    "DiscardReportChangesView",
    "SaveReportChangesView",
    "CloseReportPanelView",
    # report_detail
    "ReportDetailView",
    # report_filter_detail
    "ReportDetailFilteredView",
    # report_preview
    "ToggleAggregateView",
    "UpdateAggregateFunctionView",
    "AddColumnView",
    "RemoveColumnView",
    "AddFilterFieldView",
    "UpdateFilterOperatorView",
    "UpdateFilterValueView",
    "UpdateFilterLogicView",
    "RemoveFilterView",
    "ToggleRowGroupView",
    "RemoveRowGroupView",
    "ToggleColumnGroupView",
    "RemoveColumnGroupView",
    "RemoveAggregateColumnView",
]
