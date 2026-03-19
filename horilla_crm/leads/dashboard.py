"""Dashboard utilities for leads module."""

# Third-party imports (Django)
from django.db.models import Count
from django.utils.http import urlencode

# First-party / Horilla imports
from horilla.utils.choices import TABLE_FALLBACK_FIELD_TYPES
from horilla_dashboard.utils import DefaultDashboardGenerator
from horilla_utils.methods import get_section_info_for_model

# Local application imports
from .models import Lead


def create_lead_charts(self, queryset, model_info):
    """
    Lead-specific charts moved out of horilla_dashboard.
    """
    try:
        # ---- lead source chart ----
        if hasattr(queryset.model, "lead_source") or hasattr(queryset.model, "source"):
            field = (
                "lead_source" if hasattr(queryset.model, "lead_source") else "source"
            )

            data = queryset.values(field).annotate(count=Count("id")).order_by("-count")

            if data.exists():
                labels = [item[field] or "Unknown" for item in data]
                values = [item["count"] for item in data]

                section = get_section_info_for_model(queryset.model)
                urls = []

                for item in data:
                    value = item[field] or "Unknown"
                    query = urlencode(
                        {
                            "section": section["section"],
                            "apply_filter": "true",
                            "field": field,
                            "operator": "exact",
                            "value": value,
                        }
                    )
                    urls.append(f"{section['url']}?{query}")

                return {
                    "title": "Leads by Source",
                    "type": "funnel",
                    "data": {
                        "labels": labels,
                        "data": values,
                        "urls": urls,
                        "labelField": "Lead Source",
                    },
                }

        # ---- conversion status chart ----
        if hasattr(queryset.model, "is_converted") or hasattr(
            queryset.model, "converted"
        ):
            field = (
                "is_converted"
                if hasattr(queryset.model, "is_converted")
                else "converted"
            )

            data = queryset.values(field).annotate(count=Count("id"))

            if data.exists():
                labels = [
                    "Converted" if row[field] else "Not Converted" for row in data
                ]
                values = [row["count"] for row in data]

                return {
                    "title": "Lead Conversion Status",
                    "type": "column",
                    "data": {
                        "labels": labels,
                        "data": values,
                        "labelField": "Status",
                    },
                }

        # ---- status chart ----
        if hasattr(queryset.model, "status"):
            data = (
                queryset.values("status").annotate(count=Count("id")).order_by("-count")
            )

            if data.exists():
                labels = [row["status"] or "No Status" for row in data]
                values = [row["count"] for row in data]

                return {
                    "title": "Leads by Status",
                    "type": "funnel",
                    "data": {
                        "labels": labels,
                        "data": values,
                        "labelField": "Status",
                    },
                }

    except Exception as e:
        print("Lead chart error:", e)

    return None


def lead_table_fields(model_class):
    """Return list of {name, verbose_name} for lead table columns."""

    priority = ["first_name", "last_name", "email", "company", "lead_source"]
    fields = []
    for name in priority:
        try:
            f = model_class._meta.get_field(name)
            fields.append(
                {
                    "name": name,
                    "verbose_name": f.verbose_name or name.replace("_", " ").title(),
                }
            )
        except Exception:
            continue
    if len(fields) < 4:
        for f in model_class._meta.fields:
            if len(fields) >= 4:
                break
            if (
                f.name not in [x["name"] for x in fields]
                and f.get_internal_type() in TABLE_FALLBACK_FIELD_TYPES
            ):
                fields.append(
                    {
                        "name": f.name,
                        "verbose_name": f.verbose_name
                        or f.name.replace("_", " ").title(),
                    }
                )
    return fields


def lead_table_func(generator, model_info):
    """Generate table context for won leads."""
    filter_kwargs = (
        {"is_convert": True} if hasattr(model_info["model"], "is_convert") else {}
    )

    return generator.build_table_context(
        model_info=model_info,
        title="Won Leads",
        filter_kwargs=filter_kwargs,
        no_found_img="assets/img/not-found-list.svg",
        no_record_msg="No won leads found.",
        view_id="leads_dashboard_list",
    )


DefaultDashboardGenerator.extra_models.append(
    {
        "model": Lead,
        "name": "Leads",
        "icon": "fa-user-plus",
        "color": "blue",
        "include_kpi": True,  # Set to True to show KPI (optional, you can remove this if you don't want KPI)
        "chart_func": create_lead_charts,  # Shows chart
        "table_func": lead_table_func,  # Shows table
        "table_fields_func": lead_table_fields,
    }
)
