"""
Views for the horilla_keys app
"""

import logging
from functools import cached_property

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views import View

from horilla_core.decorators import htmx_required
from horilla_generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla_keys.filters import ShortKeyFilter
from horilla_keys.forms import ShortcutKeyForm
from horilla_keys.models import ShortcutKey

logger = logging.getLogger(__name__)


class ShortKeyView(LoginRequiredMixin, HorillaView):
    """
    TemplateView for short key view.
    """

    template_name = "short_key_view.html"
    nav_url = reverse_lazy("horilla_keys:short_key_nav")
    list_url = reverse_lazy("horilla_keys:short_key_list")


@method_decorator(htmx_required, name="dispatch")
class ShortKeyNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar fro short key
    """

    nav_title = _("Short Keys")
    search_url = reverse_lazy("horilla_keys:short_key_list")
    main_url = reverse_lazy("horilla_keys:short_key_view")
    filterset_class = ShortKeyFilter
    one_view_only = True
    all_view_types = False
    filter_option = False
    reload_option = False
    model_name = "ShortcutKey"
    model_app_label = "horilla_keys"
    nav_width = False
    gap_enabled = False

    @cached_property
    def new_button(self):
        """Return configuration for the create new shortcut key button."""
        return {
            "url": f"""{ reverse_lazy('horilla_keys:short_key_create')}?new=true""",
            "attrs": {"id": "short-key-create"},
        }


@method_decorator(htmx_required, name="dispatch")
class ShortKeyListView(LoginRequiredMixin, HorillaListView):
    """
    List view of user short key
    """

    model = ShortcutKey
    view_id = "short_key_list"
    filterset_class = ShortKeyFilter
    search_url = reverse_lazy("horilla_keys:short_key_list")
    main_url = reverse_lazy("horilla_keys:short_key_view")
    table_width = False
    bulk_update_option = False
    bulk_export_option = False
    store_ordered_ids = True
    table_height = False
    table_height_as_class = "h-[500px]"
    list_column_visibility = False

    columns = [(_("Page"), "get_page_title"), (_("Key"), "custom_key_col")]

    def get_queryset(self):
        """Return shortcut keys filtered by the logged-in user."""
        queryset = super().get_queryset()
        user_id = self.request.user
        return queryset.filter(user=user_id) if user_id else queryset.none()

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "attrs": """
                    hx-get="{get_edit_url}?new=true"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    onclick="openModal()"
                    """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "attrs": """
                    hx-post="{get_delete_url}"
                    hx-target="#deleteModeBox"
                    hx-swap="innerHTML"
                    hx-trigger="click"
                    hx-vals='{{"check_dependencies": "true"}}'
                    onclick="openDeleteModeModal()"
                """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
class ShortKeyFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    create and update from view for short key
    """

    model = ShortcutKey
    form_class = ShortcutKeyForm
    modal_height = False
    form_title = _("Short Key")
    full_width_fields = ["page"]
    hidden_fields = ["is_active", "user", "company"]

    @cached_property
    def form_url(self):
        """Return the create or update URL for the shortcut key form."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("horilla_keys:short_key_update", kwargs={"pk": pk})
        return reverse_lazy("horilla_keys:short_key_create")

    def get_initial(self):
        initial = super().get_initial()
        initial["user"] = self.request.user
        company = getattr(self.request, "active_company", None)
        initial["company"] = company
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def get(self, request, *args, **kwargs):
        pk = kwargs.get("pk")
        if pk:
            try:
                self.model.objects.get(pk=pk)
            except self.model.DoesNotExist:
                messages.error(request, "The requested data does not exist.")
                return HttpResponse("<script>$('reloadButton').click();</script>")

        return super().get(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
class ShortcutKeyDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View to handle deletion of shortcut keys."""

    model = ShortcutKey

    def get_post_delete_response(self):
        """Return HTMX response to reload shortcut key list after deletion."""
        return HttpResponse("<script>htmx.trigger('#reloadButton','click');</script>")


class ShortKeyDataView(LoginRequiredMixin, View):
    """
    View to return shortcut data as JSON for the current user.
    """

    def get(self, request, *args, **kwargs):
        """Return all shortcut keys for the logged-in user as JSON."""
        shortcuts = [
            {
                "key": sk.key,
                "page": sk.page,
                "command": sk.command.lower(),
                "section": sk.get_section(),
                "title": sk.get_page_title(),
            }
            for sk in request.user.shortcut_keys.all()
        ]

        return JsonResponse({"shortcuts": shortcuts})
