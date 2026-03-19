"""
A generic class-based view for rendering the home page.
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.functional import cached_property  # type: ignore
from django.views.generic import TemplateView

# First-party / Horilla imports
from horilla.http import HttpResponse
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla_core.forms import HolidayForm
from horilla_core.models import Holiday
from horilla_generics.views import (
    HorillaListView,
    HorillaModalDetailView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.view_holiday"), name="dispatch"
)
class HolidayView(LoginRequiredMixin, TemplateView):
    """
    TemplateView for holiday view.
    """

    template_name = "settings/holiday.html"


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.view_holiday"), name="dispatch"
)
class HolidayListView(LoginRequiredMixin, HorillaListView):
    """
    List View for holiday list.
    """

    model = Holiday
    view_id = "holiday-list-view"
    table_width = False
    bulk_select_option = False
    search_url = reverse_lazy("horilla_core:holiday_list_view")
    store_ordered_ids = True

    columns = ["name", "start_date", "end_date", "is_recurring"]

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
        if self.request.user.has_perm("horilla_core.view_holiday"):
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
            "permission": "horilla_core.change_holiday",
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
            "permission": "horilla_core.delete_holiday",
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
@method_decorator(
    permission_required_or_denied("horilla_core.delete_holiday", modal=True),
    name="dispatch",
)
class HolidayDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete View for Holiday
    """

    model = Holiday

    def get_post_delete_response(self):
        """
        Get the response after deleting a holiday.
        """

        return HttpResponse(
            "<script>$('#reloadHolidayButton').click();closeDeleteModeModal();closeDetailModal();</script>"
        )


@method_decorator(htmx_required, name="dispatch")
class HolidayFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Holiday Create/Update View
    """

    model = Holiday
    form_class = HolidayForm
    view_id = "holiday-form-view"
    form_title = "Holiday Form"
    full_width_fields = ["name"]
    return_response = HttpResponse(
        "<script>closeModal();$('#detailViewReloadButton').click();$('#tab-holidays-view').click();</script>"
    )

    @cached_property
    def form_url(self):
        """Form URL for holiday"""

        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("horilla_core:holiday_update_form", kwargs={"pk": pk})
        return reverse_lazy("horilla_core:holiday_create_form")

    def get_initial(self):
        """
        Get initial data for holiday form.
        """

        initial = super().get_initial()

        toggle = self.request.GET.get("toggle_all_users")

        if toggle == "true":
            current = self.request.GET.get("all_users", "").lower()
            current_recurring = self.request.GET.get("is_recurring", "").lower()

            initial["all_users"] = current in ["true", "on", "1"]
            initial["is_recurring"] = current_recurring in ["true", "on", "1"]
            initial["frequency"] = self.request.GET.get("frequency", "")
            initial["monthly_repeat_type"] = self.request.GET.get(
                "monthly_repeat_type", ""
            )
            initial["yearly_repeat_type"] = self.request.GET.get(
                "yearly_repeat_type", ""
            )

        elif hasattr(self, "object") and self.object:
            initial["all_users"] = self.object.all_users
            initial["is_recurring"] = self.object.is_recurring
            initial["frequency"] = getattr(self.object, "frequency", "")
            initial["monthly_repeat_type"] = getattr(
                self.object, "monthly_repeat_type", ""
            )
            initial["yearly_repeat_type"] = getattr(
                self.object, "yearly_repeat_type", ""
            )

        else:
            initial["all_users"] = False
            initial["is_recurring"] = False
            initial["frequency"] = ""
            initial["monthly_repeat_type"] = ""
            initial["yearly_repeat_type"] = ""

        initial.update(self.request.GET.dict())

        return initial


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.view_holiday"), name="dispatch"
)
class HolidayDetailView(LoginRequiredMixin, HorillaModalDetailView):
    """
    detail view of page
    """

    model = Holiday
    title = _("Details")
    header = {
        "title": "name",
        "subtitle": "",
        "avatar": "get_avatar",
    }

    body = [
        (_("Holiday Start Date"), "start_date"),
        (_("Holiday End Date"), "end_date"),
        (_("Specific Users"), "specific_users_enable"),
        (_("Recurring"), "is_recurring_holiday"),
    ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit_white.svg",
            "img_class": "w-3 h-3 flex gap-4 filter brightness-0 invert",
            "permission": "horilla_core.change_holiday",
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
            "permission": "horilla_core.delete_holiday",
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
