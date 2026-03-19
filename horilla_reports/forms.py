"""Forms for creating and validating `horilla_reports` models (Report, ReportFolder)."""

# Third-party imports (Django)
from django import forms

# First-party / Horilla imports
from horilla.urls import reverse_lazy
from horilla_generics.forms import HorillaModelForm
from horilla_reports.models import Report, ReportFolder


# Define your reports forms here
class ReportForm(HorillaModelForm):
    """Form for creating and editing reports with module, columns, and folder selection."""

    class Meta:
        """Meta options for ReportForm."""

        model = Report
        fields = ["name", "module", "folder", "selected_columns", "report_owner"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["folder"].queryset = (
            ReportFolder.objects.all()
            if self.request.user.is_superuser
            else ReportFolder.objects.filter(report_folder_owner=self.request.user)
        )

        self.fields["module"].widget.attrs.update(
            {
                "hx-get": reverse_lazy("horilla_reports:get_module_columns_htmx"),
                "hx-target": "#id_columns",
                "hx-trigger": "change",
                "hx-swap": "outerHTML",
                "hx-include": "[name='module']",
            }
        )

        self.fields["selected_columns"].widget = forms.SelectMultiple(
            attrs={
                "class": "js-example-basic-multiple headselect w-full",
                "id": "id_columns",
                "name": "selected_columns",
                "tabindex": "-1",
                "aria-hidden": "true",
                "multiple": True,
                "required": True,
            }
        )

    def clean_selected_columns(self):
        """Convert the list to comma-separated string and validate that at least one column is selected"""
        selected = self.cleaned_data.get("selected_columns", [])

        if isinstance(selected, str):
            if selected.startswith("[") and selected.endswith("]"):
                try:
                    import ast

                    selected = ast.literal_eval(selected)
                except Exception:
                    selected = [
                        item.strip().strip("'\"")
                        for item in selected.strip("[]").split(",")
                        if item.strip()
                    ]
            else:
                selected = [selected] if selected.strip() else []

        if isinstance(selected, list):
            filtered_selected = [item for item in selected if item.strip()]
            if not filtered_selected:
                raise forms.ValidationError("At least one column must be selected.")
            return ",".join(filtered_selected)

        raise forms.ValidationError("At least one column must be selected.")


class ChangeChartReportForm(HorillaModelForm):
    """Form for changing the chart type of a report."""

    class Meta:
        """Meta options for ChangeChartReportForm."""

        model = Report
        fields = ["chart_type"]

    def __init__(self, *args, **kwargs):
        self.request = kwargs.get("request")
        super().__init__(*args, **kwargs)

        total_groups = self.request.GET.get("total")

        try:
            total_groups = int(total_groups)
        except (TypeError, ValueError):
            total_groups = 0

        chart_choices = Report.CHART_TYPES

        if total_groups <= 1:
            chart_choices = [
                c
                for c in chart_choices
                if c[0]
                not in [
                    "stacked_vertical",
                    "stacked_horizontal",
                    "heatmap",
                    "sankey",
                ]
            ]

        self.fields["chart_type"].choices = chart_choices
