"""
Create and update views for activities (tasks, meetings, calls, events) in the Horilla CRM application, with dynamic form fields based on activity type and HTMX support for seamless user experience.
"""

# Standard library imports
import datetime

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.utils.functional import cached_property  # type: ignore

# First-party imports (Horilla)
from horilla.apps import apps
from horilla.db import models
from horilla.http import Http404, HttpResponse
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _
from horilla_activity.forms import (
    ActivityCreateForm,
    EventForm,
    LogCallForm,
    MeetingsForm,
)
from horilla_activity.models import Activity
from horilla_core.models import HorillaContentType
from horilla_generics.views import HorillaSingleFormView


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
                    return render(request, "403.html")

                return super().get(request, *args, **kwargs)

            except LookupError:
                return render(request, "403.html")
        if pk:
            if not self.model.objects.filter(
                owner_id=self.request.user, pk=pk
            ).first() and not self.request.user.has_perm(
                "horilla_activity.change_activity"
            ):
                return super().get(request, *args, **kwargs)
        return render(request, "403.html")

    def get_initial(self):
        """Set initial form data from GET params (object_id, model_name) for task creation."""
        initial = super().get_initial()
        object_id = self.request.GET.get("object_id")
        model_name = self.request.GET.get("model_name")
        if object_id and model_name:
            initial["object_id"] = object_id
            content_type = HorillaContentType.objects.get(model=model_name.lower())
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
        """Set initial meeting form data from GET/POST, including is_all_day and related fields."""
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
                content_type = HorillaContentType.objects.get(model=model_name.lower())
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
                    return render(request, "403.html")

                return super().get(request, *args, **kwargs)

            except LookupError:
                return render(request, "403.html")
        if pk:
            if not self.model.objects.filter(
                owner_id=self.request.user, pk=pk
            ).first() and not self.request.user.has_perm(
                "horilla_activity.change_activity"
            ):
                return super().get(request, *args, **kwargs)
        return render(request, "403.html")

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
        """Set initial call form data from GET params and default duration for new calls."""
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
            content_type = HorillaContentType.objects.get(model=model_name.lower())
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
                    return render(request, "403.html")

                return super().get(request, *args, **kwargs)

            except LookupError:
                return render(request, "403.html")
        if pk:
            if not self.model.objects.filter(
                owner_id=self.request.user, pk=pk
            ).first() and not self.request.user.has_perm(
                "horilla_activity.change_activity"
            ):
                return super().get(request, *args, **kwargs)
        return render(request, "403.html")

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
                    return render(request, "403.html")

                return super().get(request, *args, **kwargs)

            except LookupError:
                return render(request, "403.html")
        if pk:
            if not self.model.objects.filter(
                owner_id=self.request.user, pk=pk
            ).first() and not self.request.user.has_perm(
                "horilla_activity.change_activity"
            ):
                return super().get(request, *args, **kwargs)
        return render(request, "403.html")

    def get_initial(self):
        """Set initial event form data from GET/POST, including is_all_day and related fields."""
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
                content_type = HorillaContentType.objects.get(model=model_name.lower())
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


@method_decorator(htmx_required, name="dispatch")
class ActivityCreateView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Form view for creating and updating activities with dynamic fields based on activity type.
    """

    model = Activity
    form_class = ActivityCreateForm
    success_url = reverse_lazy("horilla_activity:activity_list")
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
        """Set initial form data for create/edit, including is_all_day, date, and activity_type."""
        initial = super().get_initial()

        is_create = not (self.kwargs.get("pk") or self.object)

        if self.request.method == "POST":
            initial["is_all_day"] = self.request.POST.get("is_all_day") == "on"
        else:
            object_id = self.request.GET.get("object_id")
            model_name = self.request.GET.get("model_name")
            all_day = self.request.GET.get("is_all_day")
            toggle_is_all_day = self.request.GET.get("toggle_is_all_day")
            # Use same param as Mark Unavailability (start_date_time) so clicked time is correct
            date_str = self.request.GET.get("start_date_time") or self.request.GET.get(
                "date"
            )

            if is_create:
                initial["activity_type"] = "event"
                initial["owner"] = self.request.user
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
                    clicked_datetime = datetime.datetime.fromisoformat(
                        date_str.replace("Z", "+00:00")
                    )
                    clicked_date = clicked_datetime.date()
                    clicked_time = clicked_datetime.time()
                    if clicked_time == datetime.time.min:
                        clicked_time = datetime.time(9, 0)
                    start_datetime = timezone.make_aware(
                        datetime.datetime.combine(clicked_date, clicked_time)
                    )
                    end_datetime = start_datetime + datetime.timedelta(minutes=30)

                    initial["start_datetime"] = start_datetime
                    initial["end_datetime"] = end_datetime
                except (ValueError, TypeError):
                    pass

            if object_id and model_name:
                initial["object_id"] = object_id
                content_type = HorillaContentType.objects.get(model=model_name.lower())
                initial["content_type"] = content_type.id

        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        activity_type = (
            self.request.POST.get("activity_type")
            or self.request.GET.get("activity_type")
            or (getattr(self, "object", None) and self.object.activity_type)
            or getattr(self, "activity_type", None)
        )
        if not activity_type:
            activity_type = list(self.ACTIVITY_FIELD_MAP.keys())[0]

        # Pass the list of fields that should remain visible for this activity_type
        # to the form. The form will hide all other fields.
        selected_fields = self.ACTIVITY_FIELD_MAP.get(
            activity_type, self.ACTIVITY_FIELD_MAP["event"]
        )
        kwargs["visible_fields"] = selected_fields

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
