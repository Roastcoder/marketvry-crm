"""
List views for different activity types (Task, Meeting, Call, Email, Event) in the Horilla CRM application.
"""

# Standard library imports
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.functional import cached_property  # type: ignore

# First-party / Horilla imports
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla_activity.filters import ActivityFilter
from horilla_activity.models import Activity
from horilla_core.models import HorillaContentType
from horilla_generics.views import HorillaListView
from horilla_mail.models import HorillaMail


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
    bulk_select_option = False
    paginate_by = 5
    table_class = False
    table_width = False
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
                content_type = HorillaContentType.objects.get(id=content_type_id)
                queryset = queryset.filter(
                    object_id=object_id, content_type=content_type, activity_type="task"
                )
            except HorillaContentType.DoesNotExist:
                queryset = queryset.none()
        else:
            queryset = queryset.none()

        # Pending tab = all non-completed tasks (status is workflow: not_started, etc.)
        if view_type == "completed":
            queryset = queryset.filter(status="completed")
            self.view_id = status_view_map["completed"]
        elif view_type == "pending":
            queryset = queryset.exclude(status="completed")
            self.view_id = status_view_map["pending"]

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
class MeetingListView(HorillaListView):
    """
    Meeting list view
    """

    model = Activity
    paginate_by = 10
    bulk_select_option = False
    table_class = False
    table_width = False
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
                content_type = HorillaContentType.objects.get(id=content_type_id)
                queryset = queryset.filter(
                    object_id=object_id,
                    content_type=content_type,
                    activity_type="meeting",
                )
            except HorillaContentType.DoesNotExist:
                queryset = queryset.none()
        else:
            queryset = queryset.none()

        if view_type == "completed":
            queryset = queryset.filter(status="completed")
            self.view_id = status_view_map["completed"]
        elif view_type == "pending":
            queryset = queryset.exclude(status="completed")
            self.view_id = status_view_map["pending"]

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
    bulk_select_option = False
    table_class = False
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
                content_type = HorillaContentType.objects.get(id=content_type_id)
                queryset = queryset.filter(
                    object_id=object_id,
                    content_type=content_type,
                    activity_type="log_call",
                )
            except HorillaContentType.DoesNotExist:
                queryset = queryset.none()
        else:
            queryset = queryset.none()

        if view_type == "completed":
            queryset = queryset.filter(status="completed")
            self.view_id = status_view_map["completed"]
        elif view_type == "pending":
            queryset = queryset.exclude(status="completed")
            self.view_id = status_view_map["pending"]

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
    bulk_select_option = False
    paginate_by = 10
    table_class = False
    table_width = False
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
                content_type = HorillaContentType.objects.get(id=content_type_id)
                queryset = queryset.filter(
                    object_id=object_id, content_type=content_type
                )
            except HorillaContentType.DoesNotExist:
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
    bulk_select_option = False
    paginate_by = 10
    table_class = False
    table_width = False
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
                content_type = HorillaContentType.objects.get(id=content_type_id)
                queryset = queryset.filter(
                    object_id=object_id,
                    content_type=content_type,
                    activity_type="event",
                )
            except HorillaContentType.DoesNotExist:
                queryset = queryset.none()
        else:
            queryset = queryset.none()

        if view_type == "completed":
            queryset = queryset.filter(status="completed")
            self.view_id = status_view_map["completed"]
        elif view_type == "pending":
            queryset = queryset.exclude(status="completed")
            self.view_id = status_view_map["pending"]

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object_id"] = self.kwargs.get("object_id")
        context["view_type"] = self.request.GET.get("view_type", "pending")
        return context
