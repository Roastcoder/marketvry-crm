"""Filter definitions for the `horilla_reports` app."""

from horilla_generics.filters import HorillaFilterSet
from horilla_reports.models import Report

from .models import Report  # Ensure your Report model is imported


class ReportFilter(HorillaFilterSet):
    """Filter set for filtering reports by various fields."""

    class Meta:
        """Meta options for ReportFilter."""

        model = Report
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["name"]
