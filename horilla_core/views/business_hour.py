"""
Business Hour views for Horilla CRM.
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.functional import cached_property  # type: ignore
from django.views.generic import TemplateView

from horilla.http import HttpResponse

# First-party imports (Horilla)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _

# First-party / Horilla apps
from horilla_core.forms import BusinessHourForm
from horilla_core.models import BusinessHour
from horilla_generics.views import (
    HorillaListView,
    HorillaModalDetailView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.view_businesshour"), name="dispatch"
)
class BusinessHourView(LoginRequiredMixin, TemplateView):
    """
    TemplateView for business hour view.
    """

    template_name = "settings/business_hour/business_hour.html"


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.view_businesshour"), name="dispatch"
)
class BusinessHourListView(LoginRequiredMixin, HorillaListView):
    """
    List View for business hour.
    """

    model = BusinessHour
    view_id = "business-hour-list-view"
    table_width = False
    bulk_select_option = False
    search_url = reverse_lazy("horilla_core:business_hour_list_view")
    store_ordered_ids = True

    columns = [
        "name",
        "time_zone",
        "business_hour_type",
        "week_start_day",
        (_("Default Business Hour"), "is_default_hour"),
    ]

    @cached_property
    def col_attrs(self):
        """
        Get the column attributes for the list view.
        """
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = self.request.session.get(self.ordered_ids_key, [])
        attrs = {}
        attrs = {
            "hx-get": f"{{get_detail_url}}?instance_ids={query_string}",
            "hx-target": "#detailModalBox",
            "hx-swap": "innerHTML",
            "hx-push-url": "false",
            "hx-on:click": "openDetailModal();",
            "style": "cursor:pointer",
            "class": "hover:text-primary-600",
        }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4 flex gap-4",
            "permission": "horilla_core.change_businesshour",
            "attrs": """
                hx-get="{get_edit_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
            """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "horilla_core.delete_businesshour",
            "attrs": """
                    hx-post="{get_delete_url}"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    hx-trigger="click"
                    hx-vals='{{"check_dependencies": "false"}}'
                    onclick="openModal()"
                """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
class BusinessHourFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Business Hour Create/Update View
    """

    model = BusinessHour
    form_class = BusinessHourForm
    view_id = "business-hour-form-view"
    form_title = "Business Hour Form"
    full_width_fields = ["timing_type", "week_days"]
    hidden_fields = ["company"]
    return_response = HttpResponse(
        "<script>closeModal();$('#reloadButton').click();$('#detailViewReloadButton').click();</script>"
    )

    @cached_property
    def form_url(self):
        """Form URL for business hour"""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "horilla_core:business_hour_update_form", kwargs={"pk": pk}
            )
        return reverse_lazy("horilla_core:business_hour_create_form")

    def get_initial(self):
        """
        Get initial data for business hour form.
        """
        initial = super().get_initial()
        toggle = self.request.GET.get("toggle_data")
        company = getattr(self.request, "active_company", None)
        initial["company"] = company
        if toggle == "true":
            initial["business_hour_type"] = self.request.GET.get(
                "business_hour_type", ""
            )
            initial["timing_type"] = self.request.GET.get("timing_type", "")

        elif hasattr(self, "object") and self.object:
            initial["business_hour_type"] = getattr(
                self.object, "business_hour_type", ""
            )
            initial["timing_type"] = getattr(self.object, "timing_type", "")

        else:
            initial["business_hour_type"] = ""
            initial["timing_type"] = ""

        initial.update(self.request.GET.dict())
        return initial


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.delete_businesshour", modal=True),
    name="dispatch",
)
class BusinessHourDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete View for Business Hour
    """

    model = BusinessHour

    def get_post_delete_response(self):
        """
        Get the response after deleting a business hour.
        """
        return HttpResponse(
            "<script>$('#reloadBusinessHourButton').click();closeDeleteModeModal();closeDetailModal();</script>"
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.view_businesshour"), name="dispatch"
)
class BusinessHourDetailView(LoginRequiredMixin, HorillaModalDetailView):
    """
    detail view of page
    """

    model = BusinessHour
    title = _("Details")
    header = {
        "title": "name",
        "subtitle": "",
        "avatar": "get_avatar",
    }

    body = [
        (_("Time Zone"), "time_zone"),
        (_("Hour Type"), "get_business_hour_type_display"),
        (_("Is Default"), "is_default_hour"),
        (_("Week Starts On"), "get_week_start_day_display"),
        (_("Business Days"), "get_formatted_week_days"),
    ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit_white.svg",
            "img_class": "w-3 h-3 flex gap-4 filter brightness-0 invert",
            "permission": "horilla_core.change_businesshour",
            "attrs": """
                class="w-24 justify-center px-4 py-2 bg-primary-600 text-white rounded-md text-xs flex items-center gap-2 hover:bg-primary-800 transition duration-300 disabled:cursor-not-allowed"
                hx-get="{get_edit_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal();"
            """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-3 h-3 flex gap-4 brightness-0 saturate-100",
            "image_style": "filter: invert(27%) sepia(51%) saturate(2878%) hue-rotate(346deg) brightness(104%) contrast(97%)",
            "permission": "horilla_core.delete_businesshour",
            "attrs": """
                    class="w-24 justify-center px-4 py-2 bg-[white] rounded-md text-xs flex items-center gap-2 border border-primary-500 hover:border-primary-600 transition duration-300 disabled:cursor-not-allowed text-primary-600"
                    hx-post="{get_delete_url}"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    hx-trigger="click"
                    hx-vals='{{"check_dependencies": "false"}}'
                    onclick="openModal()"
                """,
        },
    ]
