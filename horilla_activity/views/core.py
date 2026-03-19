"""
Views for the Activity module in the Horilla CRM application.
"""

# Standard library imports
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.functional import cached_property  # type: ignore
from django.views.generic import DetailView

from horilla.http import HttpResponse, RefreshResponse

# First-party imports (Horilla)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla_activity.filters import ActivityFilter
from horilla_activity.models import Activity
from horilla_activity.views.list_view import AllActivityListView
from horilla_core.models import HorillaContentType
from horilla_generics.mixins import RecentlyViewedMixin
from horilla_generics.views import (
    HorillaDetailSectionView,
    HorillaDetailTabView,
    HorillaDetailView,
    HorillaHistorySectionView,
    HorillaKanbanView,
    HorillaNavView,
    HorillaNotesAttachementSectionView,
    HorillaSingleDeleteView,
    HorillaView,
)
from horilla_utils.middlewares import _thread_local

# One source of truth — mark each field with where it should appear
ACTIVITY_TYPE_SPECIFIC_FIELDS = {
    "meeting": [
        ("title", "both"),
        ("start_datetime", "both"),
        ("end_datetime", "both"),
        ("location", "tab"),
        ("is_all_day", "tab"),
        ("participants", "tab"),
        ("meeting_host", "tab"),
    ],
    "event": [
        ("title", "both"),
        ("start_datetime", "both"),
        ("end_datetime", "both"),
        ("location", "tab"),
        ("is_all_day", "tab"),
        ("participants", "tab"),
    ],
    "task": [
        ("owner", "both"),
        ("task_priority", "both"),
        ("due_datetime", "both"),
    ],
    "log_call": [
        ("call_duration_display", "both"),
        ("call_duration_seconds", "both"),
        ("call_type", "tab"),
        ("call_purpose", "tab"),
        ("notes", "tab"),
    ],
}

COMMON_FIELDS = [
    "subject",
    "activity_type",
    "status",
    "description",
    "assigned_to",
    "related_object",
]


def get_fields_for(activity_type, view="both"):
    """
    view="summary" → only fields marked "summary" or "both"
    view="tab"     → only fields marked "tab" or "both"
    """
    fields = ACTIVITY_TYPE_SPECIFIC_FIELDS.get(activity_type, [])
    return [field for field, scope in fields if scope == view or scope == "both"]


def get_activity_detail_view_fields(activity_type):
    """
    Return the activity detail view fields
    """
    return [
        "subject",
        "activity_type",
        "status",
        "assigned_to",
        *get_fields_for(activity_type, view="summary"),  # only "summary" + "both"
    ]


def get_activity_detail_tab_fields(activity_type):
    """
    Return the activity detail tab fields
    """
    return [
        "activity_type",
        "subject",
        "status",
        "description",
        "assigned_to",
        *get_fields_for(activity_type, view="tab"),  # "tab" + "both"
    ]


@method_decorator(htmx_required, name="dispatch")
class HorillaActivitySectionView(DetailView):
    """
    Generic Activity Tab View
    """

    template_name = "activity_tab.html"
    context_object_name = "obj"

    def dispatch(self, request, *args, **kwargs):
        """Dispatch the request; fetch the object and handle errors with HX-Refresh."""
        try:
            self.object = self.get_object()
        except Exception as e:
            messages.error(self.request, e)
            return RefreshResponse(self.request)
        return super().dispatch(request, *args, **kwargs)

    def add_task_button(self):
        """Return button configuration for creating a new task."""
        return {
            "url": f"""{ reverse_lazy('horilla_activity:task_create_form')}""",
            "attrs": 'id="task-create"',
        }

    def add_meetings_button(self):
        """Return button configuration for creating a new meeting."""
        return {
            "url": f"""{ reverse_lazy('horilla_activity:meeting_create_form')}""",
            "attrs": 'id="meeting-create"',
        }

    def add_call_button(self):
        """Return button configuration for creating a new call log."""
        return {
            "url": f"""{ reverse_lazy('horilla_activity:call_create_form')}""",
            "attrs": 'id="call-create"',
        }

    def add_email_button(self):
        """Return button configuration for sending an email."""
        return {
            "url": f"""{ reverse_lazy('horilla_mail:send_mail_view')}""",
            "attrs": 'id="email-create"',
            "title": _("Send Email"),
        }

    def add_event_button(self):
        """Return button configuration for creating a new event."""
        return {
            "url": f"""{ reverse_lazy('horilla_activity:event_create_form')}""",
            "attrs": 'id="event-create"',
        }

    def get_context_data(self, **kwargs):
        """Add activity tab context: object_id, content_type, and action buttons."""
        context = super().get_context_data(**kwargs)
        pk = self.kwargs.get("pk")
        context["object_id"] = pk
        context["model_name"] = self.model._meta.model_name
        context["app_label"] = self.model._meta.app_label
        content_type = HorillaContentType.objects.get_for_model(self.model)
        context["content_type_id"] = content_type.id
        context["add_task_button"] = self.add_task_button() or {}
        context["add_meetings_button"] = self.add_meetings_button() or {}
        context["add_call_button"] = self.add_call_button() or {}
        context["add_email_button"] = self.add_email_button() or {}
        context["add_event_button"] = self.add_event_button() or {}
        return context


class ActivityView(LoginRequiredMixin, HorillaView):
    """
    Render the activity page.
    """

    nav_url = reverse_lazy("horilla_activity:activity_nav_view")
    list_url = reverse_lazy("horilla_activity:activity_list_view")
    kanban_url = reverse_lazy("horilla_activity:activity_kanban_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(
        ["horilla_activity.view_activity", "horilla_activity.view_own_activity"]
    ),
    name="dispatch",
)
class ActivityNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navigation view for managing activity.
    """

    nav_title = Activity._meta.verbose_name_plural
    search_url = reverse_lazy("horilla_activity:activity_list_view")
    main_url = reverse_lazy("horilla_activity:activity_view")
    filterset_class = ActivityFilter
    kanban_url = reverse_lazy("horilla_activity:activity_kanban_view")
    model_name = "Activity"
    model_app_label = "horilla_activity"
    enable_actions = True

    @cached_property
    def new_button(self):
        """
        URL for creating a new Activity..
        """
        if self.request.user.has_perm(
            "horilla_activity.add_activity"
        ) or self.request.user.has_perm("horilla_activity.add_own_activity"):
            return {
                "url": f"""{ reverse_lazy('horilla_activity:activity_create_form')}?new=true""",
            }
        return None


@method_decorator(
    permission_required_or_denied(
        ["horilla_activity.view_activity", "horilla_activity.view_own_activity"]
    ),
    name="dispatch",
)
class AcivityKanbanView(LoginRequiredMixin, HorillaKanbanView):
    """
    Acivity Kanban view
    """

    model = Activity
    view_id = "activity-kanban"
    filterset_class = ActivityFilter
    search_url = reverse_lazy("horilla_activity:activity_list_view")
    main_url = reverse_lazy("horilla_activity:activity_view")
    group_by_field = "status"

    actions = AllActivityListView.actions

    columns = [
        "subject",
        "activity_type",
        (_("Related To"), "related_object"),
    ]

    @cached_property
    def kanban_attrs(self):
        """
        Defines column attributes for rendering clickable Activity entries
        that load detailed views dynamically using HTMX.
        """

        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {
            "hx-get": f"{{get_detail_url}}?{query_string}",
            "hx-target": "#mainContent",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
            "hx-select": "#mainContent",
            "permission": "horilla_activity.change_activity",
            "own_permission": "horilla_activity.change_own_activity",
            "owner_field": ["owner"],
        }
        return attrs


@method_decorator(
    permission_required_or_denied(
        ["horilla_activity.view_activity", "horilla_activity.view_own_activity"]
    ),
    name="dispatch",
)
class ActivityDetailView(RecentlyViewedMixin, LoginRequiredMixin, HorillaDetailView):
    """
    Detail view for Activity
    """

    model = Activity
    pipeline_field = "status"
    tab_url = reverse_lazy("horilla_activity:activity_detail_view_tabs")

    breadcrumbs = [
        (_("Schedule"), "horilla_activity:activity_view"),
        (_("Activities"), "horilla_activity:activity_view"),
    ]

    excluded_fields = [
        "id",
        "created_at",
        "updated_at",
        "additional_info",
        "history",
        "is_active",
    ]

    actions = AllActivityListView.actions

    @classmethod
    def get_available_fields_for_selector(cls, request, model):
        """
        Method to get the available fields
        """
        pk = request.GET.get("pk")
        if not pk:
            return None
        try:
            activity = model.objects.get(pk=pk)
        except model.DoesNotExist:
            return None

        activity_type = activity.activity_type
        default_header = get_activity_detail_view_fields(activity_type)
        default_details = get_activity_detail_tab_fields(activity_type)

        type_specific = [
            field if isinstance(field, str) else field[0]
            for field in ACTIVITY_TYPE_SPECIFIC_FIELDS.get(activity_type, [])
        ]

        allowed_fields = set(COMMON_FIELDS + type_specific)
        return default_header, default_details, allowed_fields

    def get_body(self):
        """Arrange detail fields based on the activity type."""
        self.body = get_activity_detail_view_fields(self.get_object().activity_type)
        return super().get_body()


@method_decorator(
    permission_required_or_denied(
        ["horilla_activity.view_activity", "horilla_activity.view_own_activity"]
    ),
    name="dispatch",
)
@method_decorator(htmx_required, name="dispatch")
class ActivityDetailTab(LoginRequiredMixin, HorillaDetailSectionView):
    """
    Activity Detail Tab View
    """

    model = Activity

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = self.get_object()
        self.include_fields = get_activity_detail_tab_fields(obj.activity_type)

        context["body"] = self.body or self.get_default_body()
        return context


@method_decorator(
    permission_required_or_denied(
        ["horilla_activity.view_activity", "horilla_activity.view_own_activity"]
    ),
    name="dispatch",
)
class ActivityDetailViewTabView(LoginRequiredMixin, HorillaDetailTabView):
    """
    Activity Detail Tab View
    """

    def __init__(self, **kwargs):
        request = getattr(_thread_local, "request", None)
        self.request = request
        self.object_id = self.request.GET.get("object_id")
        self.urls = {
            "details": "horilla_activity:activity_details_tab",
            "notes_attachments": "horilla_activity:activity_notes_attachments",
            "history": "horilla_activity:activity_history_tab_view",
        }

        super().__init__(**kwargs)


@method_decorator(
    permission_required_or_denied(
        ["horilla_activity.view_activity", "horilla_activity.view_own_activity"]
    ),
    name="dispatch",
)
class ActivitynNotesAndAttachments(
    LoginRequiredMixin, HorillaNotesAttachementSectionView
):
    """Notes and Attachments Tab View"""

    model = Activity


@method_decorator(
    permission_required_or_denied(
        ["horilla_activity.view_activity", "horilla_activity.view_own_activity"]
    ),
    name="dispatch",
)
class ActivityHistoryTabView(LoginRequiredMixin, HorillaHistorySectionView):
    """
    History Tab View
    """

    model = Activity


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_activity.delete_activity", modal=True),
    name="dispatch",
)
class ActivityDeleteView(HorillaSingleDeleteView):
    """
    Activity delete view
    """

    model = Activity

    def get_post_delete_response(self):
        activity_type = self.object.activity_type
        if "calendar" in self.request.META.get("HTTP_REFERER", ""):
            return HttpResponse(
                "<script>$('#reloadMainContent').click();$('#reloadButton').click();</script>"
            )
        if activity_type == "task":
            return HttpResponse(
                "<script>$('#TaskTab').click();closeDeleteModeModal();"
                "$('#reloadButton').click();</script>"
            )
        if activity_type == "meeting":
            return HttpResponse(
                "<script>$'#MeetingsTab').click();closeDeleteModeModal();"
                "$('#reloadButton').click();;</script>"
            )
        if activity_type == "event":
            return HttpResponse(
                "<script>$('#EventTab').click();closeDeleteModeModal();"
                "$('#reloadButton').click();</script>"
            )
        if activity_type == "log_call":
            return HttpResponse(
                "<script>$('#CallsTab).click();closeDeleteModeModal();"
                "$('#reloadButton').click();</script>"
            )

        return HttpResponse("<script>$('#reloadButton').click();</script>")
