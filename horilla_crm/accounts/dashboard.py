"""Dashboard utilities for accounts module."""

# Standard library imports
import logging

# Third-party imports (Django)
from django.db.models import Count
from django.utils.http import urlencode

# First-party / Horilla imports
from horilla.utils.choices import TABLE_FALLBACK_FIELD_TYPES
from horilla_dashboard.utils import DefaultDashboardGenerator
from horilla_utils.methods import get_section_info_for_model

# Local application imports
from .models import Account

logger = logging.getLogger(__name__)


def account_table_fields(model_class):
    """Return list of {name, verbose_name} for account table columns."""

    priority = ["name", "account_type", "account_source", "annual_revenue"]
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


def create_account_charts(self, queryset, model_info):
    """Create account-specific charts"""
    try:
        if hasattr(queryset.model, "account_type") or hasattr(queryset.model, "type"):
            type_field = (
                "account_type" if hasattr(queryset.model, "account_type") else "type"
            )
            type_data = (
                queryset.values(type_field)
                .annotate(count=Count("id"))
                .order_by("-count")
            )

            if type_data.exists():
                labels = [item[type_field] or "Unknown" for item in type_data]
                data = [item["count"] for item in type_data]

                section_info = get_section_info_for_model(queryset.model)
                urls = []
                for item in type_data:
                    value = item[type_field] or "Unknown"
                    query = urlencode(
                        {
                            "section": section_info["section"],
                            "apply_filter": "true",
                            "field": type_field,
                            "operator": "exact",
                            "value": value,
                        }
                    )
                    urls.append(f"{section_info['url']}?{query}")

                return {
                    "title": "Accounts by Account Type",
                    "type": "pie",
                    "data": {
                        "labels": labels,
                        "data": data,
                        "urls": urls,
                        "labelField": "Account Type",
                    },
                }

    except Exception as e:
        logger.warning("Error creating campaign chart: %s", e)

    return None


DefaultDashboardGenerator.extra_models.append(
    {
        "model": Account,
        "name": "Accounts",
        "icon": "fa-building",
        "color": "indigo",
        "include_kpi": True,
        "chart_func": create_account_charts,
    }
)
