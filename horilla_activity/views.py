"""
Views for the utilities module.

This file contains the view functions or classes that handle HTTP
requests and responses for the application.
"""

import datetime
from urllib.parse import urlencode

from django.apps import apps
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property  # type: ignore
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView

from horilla.utils.shortcuts import get_object_or_404
from horilla_activity.filters import ActivityFilter
from horilla_activity.forms import EventForm
from horilla_core.decorators import (
    htmx_required,
    permission_required,
    permission_required_or_denied,
)
from horilla_generics.mixins import RecentlyViewedMixin
from horilla_generics.views import (
    HorillaDetailSectionView,
    HorillaDetailTabView,
    HorillaDetailView,
    HorillaHistorySectionView,
    HorillaKanbanView,
    HorillaListView,
    HorillaNavView,
    HorillaNotesAttachementSectionView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla_mail.models import HorillaMail
from horilla_utils.middlewares import _thread_local

from .forms import ActivityCreateForm, EventForm, LogCallForm, MeetingsForm
from .models import Activity


@method_decorator(htmx_required, name="dispatch")
class HorillaActivitySectionView(DetailView):
    """
    Generic Activity Tab View
    """

    template_name = "activity_tab.html"
    context_object_name = "obj"

    def dispatch(self, request, *args, **kwargs):
        try:
            self.object = self.get_object()
        except Exception as e:
            messages.error(self.request, e)
            return HttpResponse(headers={"HX-Refresh": "true"})
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
        context = super().get_context_data(**kwargs)
        pk = self.kwargs.get("pk")
        context["object_id"] = pk
        context["model_name"] = self.model._meta.model_name
        context["app_label"] = self.model._meta.app_label
        content_type = ContentType.objects.get_for_model(self.model)
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


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["horilla_activity.view_activity", "horilla_activity.view_own_activity"]
    ),
    name="dispatch",
)
class AllActivityListView(LoginRequiredMixin, HorillaListView):
    """
    Activity List view
    """

    model = Activity
    view_id = "activity-list"
    filterset_class = ActivityFilter
    search_url = reverse_lazy("horilla_activity:activity_list_view")
    main_url = reverse_lazy("horilla_activity:activity_view")
    bulk_update_fields = [
        "status",
    ]

    @cached_property
    def col_attrs(self):
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
            "owner_field": "owner",
        }
        return [
            {
                "subject": {
                    **attrs,
                }
            }
        ]

    columns = [
        "subject",
        "activity_type",
        (_("Related To"), "related_object"),
        "status",
    ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "horilla_activity.change_activity",
            "own_permission": "horilla_activity.change_own_activity",
            "owner_field": ["owner", "assigned_to"],
            "attrs": """
                        hx-get="{get_activity_edit_url}?new=true"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "horilla_activity.delete_activity",
            "attrs": """
                        hx-post="{get_delete_url}"
                        hx-target="#deleteModeBox"
                        hx-swap="innerHTML"
                        hx-trigger="click"
                        hx-vals='{{"check_dependencies": "true"}}'
                        onclick="openDeleteModeModal()"
                    """,
        },
        {
            "action": _("Duplicate"),
            "src": "assets/icons/duplicate.svg",
            "img_class": "w-4 h-4",
            "permission": "horilla_activity.add_activity",
            "attrs": """
                            hx-get="{get_activity_edit_url}?duplicate=true"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            """,
        },
    ]


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
    body = [
        "subject",
        "activity_type",
        (_("Related To"), "related_object"),
        "status",
        "owner",
        "assigned_to",
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

        # Base fields common to all activity types
        base_fields = [
            "activity_type",
            "subject",
            "status",
            "description",
            "assigned_to",
        ]

        # Activity type specific additional fields
        type_fields_map = {
            "meeting": [
                "title",
                "start_datetime",
                "end_datetime",
                "location",
                "is_all_day",
                "participants",
                "meeting_host",
            ],
            "event": [
                "title",
                "start_datetime",
                "end_datetime",
                "location",
                "is_all_day",
                "participants",
            ],
            "task": [
                "owner",
                "task_priority",
                "due_datetime",
            ],
            "log_call": [
                "call_duration_display",
                "call_duration_seconds",
                "call_type",
                "call_purpose",
                "notes",
            ],
        }

        # Combine base fields with type-specific fields
        self.include_fields = base_fields + type_fields_map.get(obj.activity_type, [])

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
    permission_required_or_denied(
        ["horilla_activity.view_activity", "horilla_activity.view_own_activity"]
    ),
    name="dispatch",
)
class TaskListView(LoginRequiredMixin, HorillaListView):
    """
    Task List view
    """

    model = Activity
    clear_session_button_enabled = False
    bulk_select_option = False
    paginate_by = 5
    table_class = False
    table_width = False
    table_height = False
    table_height_as_class = "h-[calc(_100vh_-_500px_)]"
    list_column_visibility = False

    columns = [
        ("Title", "title"),
        ("Due Date", "due_datetime"),
        ("Priority", "task_priority"),
        ("Status", "get_status_display"),
    ]

    def get_search_url(self):
        """
        Return the search URL for the call list view.
        """
        return reverse_lazy(
            "horilla_activity:task_list", kwargs={"object_id": self.kwargs["object_id"]}
        )

    def get_main_url(self):
        """
        Return the Main URL for the call list view.
        """
        return reverse_lazy(
            "horilla_activity:task_list", kwargs={"object_id": self.kwargs["object_id"]}
        )

    @property
    def search_url(self):
        """
        Return the search URL for the call list view.
        """
        return self.get_search_url()

    @property
    def main_url(self):
        """
        Return the main URL for the call list view.
        """
        return self.get_main_url()

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "horilla_activity.change_activity",
            "own_permission": "horilla_activity.change_own_activity",
            "owner_field": ["owner", "assigned_to"],
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
            "permission": "horilla_activity.delete_activity",
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

    def get_queryset(self):
        status_view_map = {
            "pending": "ActivityTaskListPending",
            "completed": "ActivityTaskListCompleted",
        }

        queryset = super().get_queryset()
        object_id = self.kwargs.get("object_id")
        view_type = self.request.GET.get("view_type", "pending")
        content_type_id = self.request.GET.get("content_type_id")

        if object_id and content_type_id:
            try:
                content_type = ContentType.objects.get(id=content_type_id)
                queryset = queryset.filter(
                    object_id=object_id, content_type=content_type, activity_type="task"
                )
            except ContentType.DoesNotExist:
                queryset = queryset.none()
        else:
            queryset = queryset.none()

        if view_type in status_view_map:
            queryset = queryset.filter(status=view_type)
            self.view_id = status_view_map[view_type]

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object_id"] = self.kwargs.get("object_id")
        context["view_type"] = self.request.GET.get("view_type", "pending")
        return context


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


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["horilla_activity.view_activity", "horilla_activity.view_own_activity"]
    ),
    name="dispatch",
)
class MeetingListView(HorillaListView):
    """
    Meeting list view
    """

    model = Activity
    paginate_by = 10
    clear_session_button_enabled = False
    bulk_select_option = False
    table_class = False
    table_width = False
    table_height = False
    table_height_as_class = "h-[calc(_100vh_-_500px_)]"
    list_column_visibility = False

    columns = [
        ("Title", "title"),
        ("Start Date", "get_start_date"),
        ("End Date", "get_end_date"),
        ("Status", "status"),
    ]

    def get_search_url(self):
        """
        Return the search URL for the call list view.
        """
        return reverse_lazy(
            "horilla_activity:meeting_list",
            kwargs={"object_id": self.kwargs["object_id"]},
        )

    def get_main_url(self):
        """
        Return the main URL for the call list view.
        """
        return reverse_lazy(
            "horilla_activity:meeting_list",
            kwargs={"object_id": self.kwargs["object_id"]},
        )

    @property
    def search_url(self):
        """
        Return the search URL for the call list view.
        """
        return self.get_search_url()

    @property
    def main_url(self):
        """
        Return the main URL for the call list view.
        """
        return self.get_main_url()

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "horilla_activity.change_activity",
            "own_permission": "horilla_activity.change_own_activity",
            "owner_field": ["owner", "assigned_to"],
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
            "permission": "horilla_activity.delete_activity",
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

    def get_queryset(self):
        status_view_map = {
            "pending": "ActivityMeetingListPending",
            "completed": "ActivityMeetingListCompleted",
        }

        queryset = super().get_queryset()
        object_id = self.kwargs.get("object_id")
        view_type = self.request.GET.get("view_type", "pending")
        content_type_id = self.request.GET.get("content_type_id")

        if object_id and content_type_id:
            try:
                content_type = ContentType.objects.get(id=content_type_id)
                queryset = queryset.filter(
                    object_id=object_id,
                    content_type=content_type,
                    activity_type="meeting",
                )
            except ContentType.DoesNotExist:
                queryset = queryset.none()
        else:
            queryset = queryset.none()

        if view_type in status_view_map:
            queryset = queryset.filter(status=view_type)
            self.view_id = status_view_map[view_type]

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object_id"] = self.kwargs.get("object_id")
        context["view_type"] = self.request.GET.get("view_type", "pending")
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["horilla_activity.view_activity", "horilla_activity.view_own_activity"]
    ),
    name="dispatch",
)
class CallListView(HorillaListView):
    """
    List view for call activities
    """

    model = Activity
    paginate_by = 10
    clear_session_button_enabled = False
    bulk_select_option = False
    table_class = False
    table_height = False
    table_height_as_class = "h-[calc(_100vh_-_500px_)]"
    table_width = False
    list_column_visibility = False

    columns = [
        ("Purpose", "call_purpose"),
        ("Type", "call_type"),
        ("Duration", "call_duration_display"),
        ("Status", "status"),
    ]

    def get_search_url(self):
        """
        Return the search URL for the call list view.
        """
        return reverse_lazy(
            "horilla_activity:call_list", kwargs={"object_id": self.kwargs["object_id"]}
        )

    def get_main_url(self):
        """
        Return the Main URL for the call list view.
        """
        return reverse_lazy(
            "horilla_activity:call_list", kwargs={"object_id": self.kwargs["object_id"]}
        )

    @property
    def search_url(self):
        """
        Return the search URL for the call list view.
        """
        return self.get_search_url()

    @property
    def main_url(self):
        """
        Return the main URL for the call list view.
        """
        return self.get_main_url()

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "horilla_activity.change_activity",
            "own_permission": "horilla_activity.change_own_activity",
            "owner_field": ["owner", "assigned_to"],
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
            "permission": "horilla_activity.delete_activity",
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

    def get_queryset(self):
        status_view_map = {
            "pending": "ActivityCallListPending",
            "completed": "ActivityCallListCompleted",
        }

        queryset = super().get_queryset()
        object_id = self.kwargs.get("object_id")
        view_type = self.request.GET.get("view_type", "pending")
        content_type_id = self.request.GET.get("content_type_id")

        if object_id and content_type_id:
            try:
                content_type = ContentType.objects.get(id=content_type_id)
                queryset = queryset.filter(
                    object_id=object_id,
                    content_type=content_type,
                    activity_type="log_call",
                )
            except ContentType.DoesNotExist:
                queryset = queryset.none()
        else:
            queryset = queryset.none()

        if view_type in status_view_map:
            queryset = queryset.filter(status=view_type)
            self.view_id = status_view_map[view_type]

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object_id"] = self.kwargs.get("object_id")
        context["view_type"] = self.request.GET.get("view_type", "pending")
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["horilla_activity.view_activity", "horilla_activity.view_own_activity"]
    ),
    name="dispatch",
)
class EmailListView(HorillaListView):
    """
    List view for email activities
    """

    model = HorillaMail
    clear_session_button_enabled = False
    bulk_select_option = False
    paginate_by = 10
    table_class = False
    table_width = False
    table_height = False
    table_height_as_class = "h-[calc(_100vh_-_500px_)]"
    list_column_visibility = False

    columns = [
        ("Subject", "render_subject"),
        ("Send To", "to"),
        ("Sent At", "sent_at"),
        ("Status", "get_mail_status_display"),
    ]

    def get_search_url(self):
        """
        Return the search URL for the email list view.
        """
        return reverse_lazy(
            "horilla_activity:email_list",
            kwargs={"object_id": self.kwargs["object_id"]},
        )

    @property
    def search_url(self):
        """
        Return the search URL for the email list view.
        """
        return self.get_search_url()

    action_col = {
        "draft": [
            {
                "action": "Send Email",
                "src": "assets/icons/email_black.svg",
                "img_class": "w-4 h-4",
                "attrs": """
                            hx-get="{get_edit_url}"
                            hx-target="#horillaModalBox"
                            hx-swap="innerHTML"
                            onclick="openhorillaModal()"
                            """,
            },
            {
                "action": "Delete",
                "src": "assets/icons/a4.svg",
                "img_class": "w-4 h-4",
                "attrs": """
                        hx-post="{get_delete_url}?view=draft"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        hx-trigger="click"
                        hx-vals='{{"check_dependencies": "false"}}'
                        onclick="openModal()"
                    """,
            },
        ],
        "scheduled": [
            {
                "action": "Cancel",
                "src": "assets/icons/cancel.svg",
                "img_class": "w-4 h-4",
                "attrs": """
                        hx-get="{get_edit_url}?cancel=true"
                        hx-target="#horillaModalBox"
                        hx-swap="innerHTML"
                        hx-trigger="click"
                        onclick="openhorillaModal()"
                    """,
            },
            {
                "action": "Snooze",
                "src": "assets/icons/clock.svg",
                "img_class": "w-4 h-4",
                "attrs": """
                        hx-get="{get_reschedule_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        hx-trigger="click"
                        onclick="openModal()"
                    """,
            },
            {
                "action": "Delete",
                "src": "assets/icons/a4.svg",
                "img_class": "w-4 h-4",
                "attrs": """
                        hx-post="{get_delete_url}?view=scheduled"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        hx-trigger="click"
                        hx-vals='{{"check_dependencies": "false"}}'
                        onclick="openModal()"
                    """,
            },
        ],
        "sent": [
            {
                "action": "View Email",
                "src": "assets/icons/eye1.svg",
                "img_class": "w-4 h-4",
                "attrs": """
                            hx-get="{get_view_url}"
                            hx-target="#contentModalBox"
                            hx-swap="innerHTML"
                            onclick="openContentModal()"
                            """,
            },
            {
                "action": "Delete",
                "src": "assets/icons/a4.svg",
                "img_class": "w-4 h-4",
                "attrs": """
                hx-post="{get_delete_url}?view=sent"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                hx-vals='{{"check_dependencies": "false"}}'
                onclick="openModal()"
            """,
            },
        ],
    }

    @cached_property
    def actions(self):
        """
        Return actions based on the current view type (draft, scheduled, sent).
        """
        view_type = self.request.GET.get("view_type")
        action = self.action_col.get(view_type)
        return action

    def get_queryset(self):
        status_view_map = {
            "sent": "activity-email-list-sent",
            "draft": "activity-email-list-draft",
            "scheduled": "activity-email-list-scheduled",
        }

        queryset = super().get_queryset()
        object_id = self.kwargs.get("object_id")
        view_type = self.request.GET.get("view_type", "sent")
        content_type_id = self.request.GET.get("content_type_id")

        if object_id and content_type_id:
            try:
                content_type = ContentType.objects.get(id=content_type_id)
                queryset = queryset.filter(
                    object_id=object_id, content_type=content_type
                )
            except ContentType.DoesNotExist:
                queryset = queryset.none()
        else:
            queryset = queryset.none()

        if view_type in status_view_map:
            queryset = queryset.filter(mail_status=view_type)
            self.view_id = status_view_map[view_type]

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object_id"] = self.kwargs.get("object_id")
        context["view_type"] = self.request.GET.get("view_type", "sent")
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["horilla_activity.view_activity", "horilla_activity.view_own_activity"]
    ),
    name="dispatch",
)
class EventListView(HorillaListView):
    """
    List view for event activities
    """

    model = Activity
    clear_session_button_enabled = False
    bulk_select_option = False
    paginate_by = 10
    table_class = False
    table_width = False
    table_height = False
    table_height_as_class = "h-[calc(_100vh_-_500px_)]"
    list_column_visibility = False

    columns = [
        ("Title", "title"),
        ("Start Date", "get_start_date"),
        ("End Date", "get_end_date"),
        ("Location", "location"),
        # ("All day Event","is_all_day"),
        ("Status", "get_status_display"),
    ]

    def get_search_url(self):
        """
        Return the search URL for the event list view.
        """
        return reverse_lazy(
            "horilla_activity:event_list",
            kwargs={"object_id": self.kwargs["object_id"]},
        )

    @property
    def search_url(self):
        """
        Return the search URL for the event list view.
        """
        return self.get_search_url()

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "horilla_activity.change_activity",
            "own_permission": "horilla_activity.change_own_activity",
            "owner_field": ["owner", "assigned_to"],
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
            "permission": "horilla_activity.delete_activity",
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

    def get_queryset(self):
        status_view_map = {
            "pending": "ActivityEventListPending",
            "completed": "ActivityEventListCompleted",
        }

        queryset = super().get_queryset()
        object_id = self.kwargs.get("object_id")
        view_type = self.request.GET.get("view_type", "pending")
        content_type_id = self.request.GET.get("content_type_id")

        if object_id and content_type_id:
            try:
                content_type = ContentType.objects.get(id=content_type_id)
                queryset = queryset.filter(
                    object_id=object_id,
                    content_type=content_type,
                    activity_type="event",
                )
            except ContentType.DoesNotExist:
                queryset = queryset.none()
        else:
            queryset = queryset.none()

        if view_type in status_view_map:
            queryset = queryset.filter(status=view_type)
            self.view_id = status_view_map[view_type]

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object_id"] = self.kwargs.get("object_id")
        context["view_type"] = self.request.GET.get("view_type", "pending")
        return context


@method_decorator(htmx_required, name="dispatch")
class TaskCreateForm(LoginRequiredMixin, HorillaSingleFormView):
    """
    Form view for task activity
    """

    model = Activity
    full_width_fields = ["description"]
    modal_height = False
    hidden_fields = ["object_id", "content_type", "activity_type"]
    save_and_new = False
    fields = [
        "object_id",
        "content_type",
        "title",
        "subject",
        "owner",
        "task_priority",
        "assigned_to",
        "due_datetime",
        "status",
        "description",
        "activity_type",
    ]

    @cached_property
    def form_url(self):
        """
        Return the form URL for creating or updating a task.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("horilla_activity:task_update_form", kwargs={"pk": pk})
        return reverse_lazy("horilla_activity:task_create_form")

    def get(self, request, *args, **kwargs):
        pk = self.kwargs.get("pk")
        object_id = request.GET.get("object_id")
        model_name = request.GET.get("model_name")
        app_label = request.GET.get("app_label")

        if pk:
            try:
                activity = get_object_or_404(Activity, pk=pk)
            except Http404:
                messages.error(
                    request,
                    f"{self.model._meta.verbose_name.title()} not found or no longer exists.",
                )
                return HttpResponse(
                    "<script>$('#reloadButton').click();closeModal();</script>"
                )
            object_id = object_id or activity.object_id
            model_name = model_name or activity.content_type.model
            app_label = app_label or activity.content_type.app_label

        if object_id and model_name:
            try:
                model_class = apps.get_model(app_label=app_label, model_name=model_name)

                try:
                    instance = get_object_or_404(model_class, pk=object_id)
                except Http404:
                    messages.error(
                        request,
                        f"{self.model._meta.verbose_name.title()} not found or no longer exists.",
                    )
                    return HttpResponse(
                        "<script>$('#reloadButton').click();closeModal();</script>"
                    )

                owner_fields = getattr(model_class, "OWNER_FIELDS", ["owner"])
                user_is_owner = False

                for field in owner_fields:
                    if hasattr(instance, field):
                        value = getattr(instance, field)

                        if isinstance(value, models.Model):
                            if value.id == request.user.id:
                                user_is_owner = True
                                break
                        elif hasattr(value, "all"):
                            if request.user in value.all():
                                user_is_owner = True
                                break

                if not user_is_owner and not request.user.has_perm(
                    "horilla_activity.add_activity"
                ):
                    return render(request, "error/403.html")

                return super().get(request, *args, **kwargs)

            except LookupError:
                return render(request, "error/403.html")
        if pk:
            if not self.model.objects.filter(
                owner_id=self.request.user, pk=pk
            ).first() and not self.request.user.has_perm(
                "horilla_activity.change_activity"
            ):
                return super().get(request, *args, **kwargs)
        return render(request, "error/403.html")

    def get_initial(self):
        initial = super().get_initial()
        object_id = self.request.GET.get("object_id")
        model_name = self.request.GET.get("model_name")
        if object_id and model_name:
            initial["object_id"] = object_id
            content_type = ContentType.objects.get(model=model_name.lower())
            initial["content_type"] = content_type.id
            initial["owner"] = self.request.user
            initial["activity_type"] = "task"
        return initial

    def form_valid(self, form):
        """
        Handle form submission and save the task.
        """
        super().form_valid(form)
        return HttpResponse(
            "<script>htmx.trigger('#reloadButton','click');closeModal();</script>"
        )


@method_decorator(htmx_required, name="dispatch")
class MeetingsCreateForm(LoginRequiredMixin, HorillaSingleFormView):
    """
    Form view for meeting activity
    """

    model = Activity
    form_class = MeetingsForm
    save_and_new = False
    fields = [
        "object_id",
        "content_type",
        "title",
        "subject",
        "start_datetime",
        "end_datetime",
        "status",
        "owner",
        "participants",
        "meeting_host",
        "is_all_day",
        "activity_type",
    ]
    modal_height = False

    @cached_property
    def form_url(self):
        """
        Return the form URL for creating or updating a meeting.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "horilla_activity:meeting_update_form", kwargs={"pk": pk}
            )
        return reverse_lazy("horilla_activity:meeting_create_form")

    def get_initial(self):
        initial = super().get_initial()
        if self.request.method == "POST":
            initial["is_all_day"] = self.request.POST.get("is_all_day") == "on"
        else:
            object_id = self.request.GET.get("object_id")
            model_name = self.request.GET.get("model_name")
            all_day = self.request.GET.get("is_all_day")
            toggle_is_all_day = self.request.GET.get("toggle_is_all_day")

            # If toggle_is_all_day is present and we're in edit mode, force is_all_day to False
            if toggle_is_all_day == "true" and self.kwargs.get("pk"):
                initial["is_all_day"] = False

            elif all_day is not None:
                initial["is_all_day"] = all_day == "on"

            elif hasattr(self, "object") and self.object:
                initial["is_all_day"] = self.object.is_all_day

            if object_id and model_name:
                initial["object_id"] = object_id
                content_type = ContentType.objects.get(model=model_name.lower())
                initial["content_type"] = content_type.id
                initial["activity_type"] = "meeting"
                initial["owner"] = self.request.user

        return initial

    def get(self, request, *args, **kwargs):
        pk = self.kwargs.get("pk")
        object_id = request.GET.get("object_id")
        model_name = request.GET.get("model_name")
        app_label = request.GET.get("app_label")

        if pk:
            try:
                activity = get_object_or_404(Activity, pk=pk)
            except Http404:
                messages.error(
                    request,
                    f"{self.model._meta.verbose_name.title()} not found or no longer exists.",
                )
                return HttpResponse(
                    "<script>$('#reloadButton').click();closeModal();</script>"
                )
            object_id = object_id or activity.object_id
            model_name = model_name or activity.content_type.model
            app_label = app_label or activity.content_type.app_label

        if object_id and model_name:
            try:
                model_class = apps.get_model(app_label=app_label, model_name=model_name)
                try:
                    instance = get_object_or_404(model_class, pk=object_id)
                except Http404:
                    messages.error(
                        request,
                        f"{self.model._meta.verbose_name.title()} not found or no longer exists.",
                    )
                    return HttpResponse(
                        "<script>$('#reloadButton').click();closeModal();</script>"
                    )

                owner_fields = getattr(model_class, "OWNER_FIELDS", ["owner"])
                user_is_owner = False

                for field in owner_fields:
                    if hasattr(instance, field):
                        value = getattr(instance, field)

                        if isinstance(value, models.Model):
                            if value.id == request.user.id:
                                user_is_owner = True
                                break
                        elif hasattr(value, "all"):
                            if request.user in value.all():
                                user_is_owner = True
                                break

                if not user_is_owner and not request.user.has_perm(
                    "horilla_activity.add_activity"
                ):
                    return render(request, "error/403.html")

                return super().get(request, *args, **kwargs)

            except LookupError:
                return render(request, "error/403.html")
        if pk:
            if not self.model.objects.filter(
                owner_id=self.request.user, pk=pk
            ).first() and not self.request.user.has_perm(
                "horilla_activity.change_activity"
            ):
                return super().get(request, *args, **kwargs)
        return render(request, "error/403.html")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.method == "POST":
            return kwargs

        initial = self.get_initial()
        get_data = self.request.GET.dict()
        for key, value in get_data.items():
            if value:
                initial[key] = value
        kwargs["initial"] = initial
        return kwargs

    def form_valid(self, form):
        """
        Handle form submission and save the meeting.
        """
        super().form_valid(form)
        return HttpResponse(
            "<script>htmx.trigger('#MeetingsTab','click');closeModal();</script>"
        )


@method_decorator(htmx_required, name="dispatch")
class CallCreateForm(LoginRequiredMixin, HorillaSingleFormView):
    """
    Form view for call activity
    """

    model = Activity
    form_class = LogCallForm
    modal_height = False
    full_width_fields = ["notes"]
    save_and_new = False

    fields = [
        "object_id",
        "content_type",
        "subject",
        "owner",
        "call_purpose",
        "call_type",
        "call_duration_display",
        "status",
        "notes",
        "activity_type",
    ]

    @cached_property
    def form_url(self):
        """
        Return the form URL for creating or updating a call.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("horilla_activity:call_update_form", kwargs={"pk": pk})
        return reverse_lazy("horilla_activity:call_create_form")

    def get_initial(self):
        initial = super().get_initial()
        object_id = self.request.GET.get("object_id")
        model_name = self.request.GET.get("model_name")
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if not pk:
            initial["call_duration_display"] = (
                "00:00:00"  # Default duration for creation
            )

        if object_id and model_name:
            initial["object_id"] = object_id
            content_type = ContentType.objects.get(model=model_name.lower())
            initial["content_type"] = content_type.id
            initial["activity_type"] = "log_call"
            initial["owner"] = self.request.user

        return initial

    def get(self, request, *args, **kwargs):
        pk = self.kwargs.get("pk")
        object_id = request.GET.get("object_id")
        model_name = request.GET.get("model_name")
        app_label = request.GET.get("app_label")

        if pk:
            try:
                activity = get_object_or_404(Activity, pk=pk)
            except Http404:
                messages.error(
                    request,
                    f"{self.model._meta.verbose_name.title()} not found or no longer exists.",
                )
                return HttpResponse(
                    "<script>$('#reloadButton').click();closeModal();</script>"
                )
            object_id = object_id or activity.object_id
            model_name = model_name or activity.content_type.model
            app_label = app_label or activity.content_type.app_label

        if object_id and model_name:
            try:
                model_class = apps.get_model(app_label=app_label, model_name=model_name)
                try:
                    instance = get_object_or_404(model_class, pk=object_id)
                except Http404:
                    messages.error(
                        request,
                        f"{self.model._meta.verbose_name.title()} not found or no longer exists.",
                    )
                    return HttpResponse(
                        "<script>$('#reloadButton').click();closeModal();</script>"
                    )

                owner_fields = getattr(model_class, "OWNER_FIELDS", ["owner"])
                user_is_owner = False

                for field in owner_fields:
                    if hasattr(instance, field):
                        value = getattr(instance, field)

                        if isinstance(value, models.Model):
                            if value.id == request.user.id:
                                user_is_owner = True
                                break
                        elif hasattr(value, "all"):
                            if request.user in value.all():
                                user_is_owner = True
                                break

                if not user_is_owner and not request.user.has_perm(
                    "horilla_activity.add_activity"
                ):
                    return render(request, "error/403.html")

                return super().get(request, *args, **kwargs)

            except LookupError:
                return render(request, "error/403.html")
        if pk:
            if not self.model.objects.filter(
                owner_id=self.request.user, pk=pk
            ).first() and not self.request.user.has_perm(
                "horilla_activity.change_activity"
            ):
                return super().get(request, *args, **kwargs)
        return render(request, "error/403.html")

    def form_valid(self, form):
        """
        Handle form submission and save the meeting.
        """
        super().form_valid(form)
        return HttpResponse(
            "<script>htmx.trigger('#CallsTab','click');closeModal();</script>"
        )


@method_decorator(htmx_required, name="dispatch")
class EventCreateForm(LoginRequiredMixin, HorillaSingleFormView):
    """
    Form view for event activity
    """

    model = Activity
    form_class = EventForm
    modal_height = False
    full_width_fields = ["notes"]
    save_and_new = False

    fields = [
        "object_id",
        "content_type",
        "title",
        "subject",
        "owner",
        "start_datetime",
        "end_datetime",
        "location",
        "assigned_to",
        "status",
        "is_all_day",
        "activity_type",
    ]

    @cached_property
    def form_url(self):
        """
        Return the form URL for creating or updating an event.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("horilla_activity:event_update_form", kwargs={"pk": pk})
        return reverse_lazy("horilla_activity:event_create_form")

    def get(self, request, *args, **kwargs):
        pk = self.kwargs.get("pk")
        object_id = request.GET.get("object_id")
        model_name = request.GET.get("model_name")
        app_label = request.GET.get("app_label")

        if pk:
            try:
                activity = get_object_or_404(Activity, pk=pk)
            except Http404:
                messages.error(
                    request,
                    f"{self.model._meta.verbose_name.title()} not found or no longer exists.",
                )
                return HttpResponse(
                    "<script>$('#reloadButton').click();closeModal();</script>"
                )
            object_id = object_id or activity.object_id
            model_name = model_name or activity.content_type.model
            app_label = app_label or activity.content_type.app_label

        if object_id and model_name:
            try:
                model_class = apps.get_model(app_label=app_label, model_name=model_name)

                try:
                    instance = get_object_or_404(model_class, pk=object_id)
                except Http404:
                    messages.error(
                        request,
                        f"{self.model._meta.verbose_name.title()} not found or no longer exists.",
                    )
                    return HttpResponse(
                        "<script>$('#reloadButton').click();closeModal();</script>"
                    )

                owner_fields = getattr(model_class, "OWNER_FIELDS", ["owner"])
                user_is_owner = False

                for field in owner_fields:
                    if hasattr(instance, field):
                        value = getattr(instance, field)

                        if isinstance(value, models.Model):
                            if value.id == request.user.id:
                                user_is_owner = True
                                break
                        elif hasattr(value, "all"):
                            if request.user in value.all():
                                user_is_owner = True
                                break

                if not user_is_owner and not request.user.has_perm(
                    "horilla_activity.add_activity"
                ):
                    return render(request, "error/403.html")

                return super().get(request, *args, **kwargs)

            except LookupError:
                return render(request, "error/403.html")
        if pk:
            if not self.model.objects.filter(
                owner_id=self.request.user, pk=pk
            ).first() and not self.request.user.has_perm(
                "horilla_activity.change_activity"
            ):
                return super().get(request, *args, **kwargs)
        return render(request, "error/403.html")

    def get_initial(self):
        initial = super().get_initial()
        if self.request.method == "POST":
            initial["is_all_day"] = self.request.POST.get("is_all_day") == "on"
        else:
            object_id = self.request.GET.get("object_id")
            model_name = self.request.GET.get("model_name")
            all_day = self.request.GET.get("is_all_day")
            toggle_is_all_day = self.request.GET.get("toggle_is_all_day")

            # If toggle_is_all_day is present and we're in edit mode, force is_all_day to False
            if toggle_is_all_day == "true" and self.kwargs.get("pk"):
                initial["is_all_day"] = False

            # If we have GET parameter for is_all_day, use it
            elif all_day is not None:
                initial["is_all_day"] = all_day == "on"

            # If we're editing an existing event and no GET parameter, use the model value
            elif hasattr(self, "object") and self.object:
                initial["is_all_day"] = self.object.is_all_day

            if object_id and model_name:
                initial["object_id"] = object_id
                content_type = ContentType.objects.get(model=model_name.lower())
                initial["content_type"] = content_type.id
                initial["activity_type"] = "event"
                initial["owner"] = self.request.user

        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.method == "POST":
            return kwargs

        initial = self.get_initial()
        get_data = self.request.GET.dict()
        for key, value in get_data.items():
            if value:
                initial[key] = value
        kwargs["initial"] = initial
        return kwargs

    def form_valid(self, form):
        """
        Handle form submission and save the meeting.
        """

        super().form_valid(form)
        return HttpResponse(
            "<script>htmx.trigger('#EventTab','click');closeModal();</script>"
        )

    def form_invalid(self, form):

        # Render the form with errors for HTMX to update the UI
        return self.render_to_response(self.get_context_data(form=form))


@method_decorator(htmx_required, name="dispatch")
class ActivityCreateView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Form view for creating and updating activities with dynamic fields based on activity type.
    """

    model = Activity
    form_class = ActivityCreateForm
    success_url = reverse_lazy("horilla_activity:activity_list")
    form_title = "Create Activity"
    view_id = "activity-form-view"
    save_and_new = False
    full_width_fields = ["description", "notes"]

    ACTIVITY_FIELD_MAP = {
        "event": [
            "activity_type",
            "subject",
            "content_type",
            "object_id",
            "owner",
            "status",
            "title",
            "start_datetime",
            "end_datetime",
            "location",
            "is_all_day",
            "assigned_to",
            "participants",
            "description",
        ],
        "meeting": [
            "activity_type",
            "subject",
            "content_type",
            "object_id",
            "owner",
            "status",
            "title",
            "start_datetime",
            "end_datetime",
            "location",
            "is_all_day",
            "assigned_to",
            "participants",
            "meeting_host",
            "description",
        ],
        "task": [
            "activity_type",
            "subject",
            "content_type",
            "object_id",
            "status",
            "owner",
            "task_priority",
            "due_datetime",
            "description",
        ],
        "email": [
            "activity_type",
            "subject",
            "content_type",
            "object_id",
            "status",
            "sender",
            "to_email",
            "email_subject",
            "body",
            "bcc",
            "sent_at",
            "scheduled_at",
            "is_sent",
            "description",
        ],
        "log_call": [
            "activity_type",
            "subject",
            "content_type",
            "object_id",
            "owner",
            "status",
            "call_duration_display",
            "call_duration_seconds",
            "call_type",
            "call_purpose",
            "notes",
            "description",
        ],
    }

    def get_initial(self):
        initial = super().get_initial()

        is_create = not (self.kwargs.get("pk") or self.object)

        if self.request.method == "POST":
            initial["is_all_day"] = self.request.POST.get("is_all_day") == "on"
        else:
            object_id = self.request.GET.get("object_id")
            model_name = self.request.GET.get("model_name")
            all_day = self.request.GET.get("is_all_day")
            toggle_is_all_day = self.request.GET.get("toggle_is_all_day")
            date_str = self.request.GET.get("date")

            if is_create:
                initial["activity_type"] = "event"
            else:
                initial["activity_type"] = getattr(
                    self.object, "activity_type", None
                ) or initial.get("activity_type", "event")

            if toggle_is_all_day == "true" and self.kwargs.get("pk"):
                initial["is_all_day"] = False
            elif all_day is not None:
                initial["is_all_day"] = all_day == "on"
            elif hasattr(self, "object") and self.object:
                initial["is_all_day"] = self.object.is_all_day

            if is_create and date_str:
                try:
                    clicked_datetime = datetime.datetime.fromisoformat(date_str)
                    clicked_date = clicked_datetime.date()

                    if clicked_datetime.time() == datetime.time.min:
                        clicked_time = datetime.time(9, 0)
                    else:
                        clicked_time = clicked_datetime.time()

                    start_datetime = timezone.make_aware(
                        datetime.datetime.combine(clicked_date, clicked_time)
                    )
                    end_datetime = start_datetime + datetime.timedelta(hours=1)

                    initial["start_datetime"] = start_datetime
                    initial["end_datetime"] = end_datetime
                except (ValueError, TypeError):
                    pass

            if object_id and model_name:
                initial["object_id"] = object_id
                content_type = ContentType.objects.get(model=model_name.lower())
                initial["content_type"] = content_type.id

        return initial

    def get_form_class(self):
        activity_type = (
            self.request.POST.get("activity_type")
            or self.request.GET.get("activity_type")
            or (getattr(self, "object", None) and self.object.activity_type)
            or getattr(self, "activity_type", None)
        )
        if not activity_type:
            activity_type = list(self.ACTIVITY_FIELD_MAP.keys())[0]

        selected_fields = self.ACTIVITY_FIELD_MAP.get(
            activity_type, self.ACTIVITY_FIELD_MAP["event"]
        )

        class DynamicActivityForm(ActivityCreateForm):
            """
            Creates and returns a dynamically generated Activity form class with fields and widgets
            customized based on the selected fields and the base ActivityCreateForm configuration.
            """

            class Meta(ActivityCreateForm.Meta):
                """
                Defines dynamic Meta options for the form, setting the model, fields, and widgets
                based on the selected fields and the base ActivityCreateForm configuration.
                """

                model = self.model
                fields = selected_fields
                widgets = (
                    ActivityCreateForm.Meta.widgets.copy()
                    if hasattr(ActivityCreateForm.Meta, "widgets")
                    else {}
                )

        return DynamicActivityForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        activity_type = (
            self.request.POST.get("activity_type")
            or self.request.GET.get("activity_type")
            or (getattr(self, "object", None) and self.object.activity_type)
        )
        if activity_type:
            kwargs["initial"] = kwargs.get("initial", {})
            kwargs["initial"]["activity_type"] = activity_type

        if self.request.method == "GET":
            kwargs["initial"] = kwargs.get("initial", {})
            for field in self.ACTIVITY_FIELD_MAP.get(
                activity_type, self.ACTIVITY_FIELD_MAP["event"]
            ):
                if field in self.request.GET:
                    value = self.request.GET.get(field)
                    if value:
                        if field in ["start_datetime", "end_datetime"] and kwargs[
                            "initial"
                        ].get("is_all_day"):
                            continue
                        kwargs["initial"][field] = value
                elif field in self.request.GET.getlist(field):
                    values = self.request.GET.getlist(field)
                    if values:
                        kwargs["initial"][field] = values
            if "content_type" in self.request.GET:
                kwargs["initial"]["content_type"] = self.request.GET.get("content_type")
            if "object_id" in self.request.GET:
                kwargs["initial"]["object_id"] = self.request.GET.get("object_id")

            if (
                self.duplicate_mode
                and "initial" in kwargs
                and "content_type" in kwargs["initial"]
            ):
                content_type_value = kwargs["initial"]["content_type"]
                if hasattr(content_type_value, "id"):
                    kwargs["initial"]["content_type"] = content_type_value.id
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form_url"] = self.form_url
        context["modal_height"] = True
        context["view_id"] = self.view_id
        return context

    @cached_property
    def form_url(self):
        """
        Returns the appropriate form URL for creating or editing an Activity
        based on the presence of a primary key (pk).
        """

        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "horilla_activity:activity_edit_form", kwargs={"pk": pk}
            )
        return reverse_lazy("horilla_activity:activity_create_form")

    def form_valid(self, form):
        """
        Handle form submission and save the meeting.
        """

        super().form_valid(form)
        if "calendar-view" in self.request.META.get("HTTP_REFERER"):
            return HttpResponse(
                "<script>$('#reloadMainContent').click();closeModal();</script>"
            )
        return HttpResponse("<script>$('#reloadButton').click();closeModal();</script>")
