"""Views for the calendar app in Horilla"""

# Standard library imports
import datetime
import json

from django.contrib import messages

# Third-party imports (Django)
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.utils.functional import cached_property  # type: ignore
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView

from horilla.http import HttpResponse, JsonResponse
from horilla.shortcuts import render

# First-party imports (Horilla)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext as _
from horilla_activity.models import Activity

# First-party / Horilla apps
from horilla_core.utils import get_user_field_permission
from horilla_generics.templatetags.horilla_tags._shared import format_datetime_value
from horilla_generics.views import HorillaSingleDeleteView, HorillaSingleFormView
from horilla_utils.middlewares import _thread_local

from .models import UserAvailability, UserCalendarPreference


class CalendarView(LoginRequiredMixin, TemplateView):
    """View to display the calendar with user preferences."""

    template_name = "calendar.html"

    def get_context_data(self, **kwargs):
        """Build context with calendar types and user color preferences for display."""
        context = super().get_context_data(**kwargs)
        context["calendars"] = [
            {"id": "task", "name": _("Tasks"), "default_color": "#3B82F6"},
            {"id": "event", "name": _("Events"), "default_color": "#10B981"},
            {"id": "meeting", "name": _("Meetings"), "default_color": "#EF4444"},
            {
                "id": "unavailability",
                "name": _("Unavailability"),
                "default_color": "#F5E614",
            },
        ]
        preferences = UserCalendarPreference.objects.filter(user=self.request.user)
        context["user_preferences"] = {
            pref.calendar_type: pref.color for pref in preferences
        }

        display_only = self.request.GET.get("display_only")
        if display_only and display_only in [cal["id"] for cal in context["calendars"]]:
            UserCalendarPreference.objects.filter(user=self.request.user).update(
                is_selected=False
            )
            UserCalendarPreference.objects.filter(
                user=self.request.user, calendar_type=display_only
            ).update(is_selected=True)
            for calendar in context["calendars"]:
                calendar["selected"] = calendar["id"] == display_only
        else:
            for calendar in context["calendars"]:
                pref = preferences.filter(calendar_type=calendar["id"]).first()
                calendar["selected"] = pref.is_selected if pref else True

        status_field_permission = get_user_field_permission(
            self.request.user, Activity, "status"
        )
        context["status_field_permission"] = status_field_permission

        return context


@method_decorator(csrf_exempt, name="dispatch")
class SaveCalendarPreferencesView(LoginRequiredMixin, View):
    """View to save user calendar preferences via AJAX."""

    def post(self, request, *args, **kwargs):
        """Handle AJAX POST request to save calendar preferences."""
        try:
            data = json.loads(request.body)
            calendar_types = data.get("calendar_types", [])
            calendar_type = data.get("calendar_type")
            color = data.get("color")
            valid_types = {"task", "event", "meeting", "unavailability"}
            company = getattr(request, "active_company", None) or request.user.company

            if calendar_type and color and calendar_type in valid_types:
                preference, created = UserCalendarPreference.objects.update_or_create(
                    user=request.user,
                    calendar_type=calendar_type,
                    defaults={"color": color, "is_selected": True, "company": company},
                )
                if not created:
                    preference.color = color
                    if not preference.company:
                        preference.company = company
                    preference.save()

            if "calendar_types" in data:
                UserCalendarPreference.objects.filter(user=request.user).update(
                    is_selected=False
                )
                if calendar_types:
                    if not all(ct in valid_types for ct in calendar_types):
                        return JsonResponse(
                            {"status": "error", "message": "Invalid calendar type"},
                            status=400,
                        )
                    for ct in calendar_types:
                        defaults = {
                            "is_selected": True,
                            "company": company,
                        }
                        if not UserCalendarPreference.objects.filter(
                            user=request.user, calendar_type=ct
                        ).exists():
                            defaults["color"] = (
                                "#F5E614" if ct == "unavailability" else "#000000"
                            )
                        preference, created = (
                            UserCalendarPreference.objects.update_or_create(
                                user=request.user,
                                calendar_type=ct,
                                company=company,
                                defaults=defaults,
                            )
                        )

                        if not created:
                            preference.is_selected = True
                            if not preference.company:
                                preference.company = company
                            preference.save(update_fields=["is_selected", "company"])

            messages.success(request, _("Preferences saved successfully"))

            return JsonResponse(
                {"status": "success", "message": "Preferences saved successfully"}
            )
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)


class GetCalendarEventsView(LoginRequiredMixin, View):
    """View to fetch calendar events based on user preferences."""

    def get(self, request, *args, **kwargs):
        """Handle AJAX GET request to fetch calendar events."""

        if not request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return render(request, "405.html", status=405)

        try:
            selected_types = request.GET.getlist("calendar_types[]")
            if not selected_types and "calendar_types[]" in request.GET:
                return JsonResponse({"status": "success", "events": []})

            if not selected_types:
                selected_types = UserCalendarPreference.objects.filter(
                    user=request.user, is_selected=True
                ).values_list("calendar_type", flat=True)
                if not selected_types:
                    selected_types = ["task", "event", "meeting", "unavailability"]

            events = []
            if selected_types:
                # Fetch Activity events
                activity_types = [t for t in selected_types if t != "unavailability"]
                if activity_types:
                    activities = (
                        Activity.objects.filter(
                            activity_type__in=activity_types,
                            assigned_to=request.user,
                        )
                        | Activity.objects.filter(
                            activity_type__in=activity_types, participants=request.user
                        )
                        | Activity.objects.filter(
                            activity_type__in=activity_types, owner=request.user
                        )
                        | Activity.objects.filter(
                            activity_type__in=activity_types, meeting_host=request.user
                        )
                    )

                    for activity in activities.distinct():
                        start_dt = activity.get_start_date()
                        end_dt = activity.get_end_date()
                        start_display = (
                            format_datetime_value(start_dt, user=request.user)
                            if not isinstance(start_dt, str)
                            else start_dt
                        )
                        end_display = (
                            format_datetime_value(end_dt, user=request.user)
                            if not isinstance(end_dt, str) and end_dt
                            else None
                        )
                        due_date_display = None
                        if activity.activity_type == "task" and activity.due_datetime:
                            due_date_display = format_datetime_value(
                                activity.due_datetime, user=request.user
                            )
                        event = {
                            "title": activity.title or activity.subject,
                            "start": (
                                start_dt.isoformat()
                                if not isinstance(start_dt, str)
                                else activity.created_at.isoformat()
                            ),
                            "end": (
                                end_dt.isoformat()
                                if not isinstance(end_dt, str) and end_dt
                                else None
                            ),
                            "calendarType": activity.activity_type,
                            "activity_type_display": activity.get_activity_type_display(),
                            "description": activity.description or "",
                            "subject": activity.subject or "",
                            "assignedTo": list(
                                activity.assigned_to.values(
                                    "id", "first_name", "last_name", "email"
                                )
                            ),
                            "status": activity.status,
                            "status_display": activity.get_status_display(),
                            "start_display": start_display,
                            "end_display": end_display,
                            "due_date_display": due_date_display,
                            "id": activity.id,
                            "url": (
                                activity.get_activity_edit_url()
                                if activity.activity_type != "email"
                                else None
                            ),
                            "deleteUrl": (
                                activity.get_delete_url()
                                if activity.activity_type != "email"
                                else None
                            ),
                            "detailUrl": (
                                activity.get_detail_url()
                                if activity.activity_type != "email"
                                else None
                            ),
                            "dueDate": (
                                activity.due_datetime.isoformat()
                                if activity.activity_type == "task"
                                and activity.due_datetime
                                else None
                            ),
                            "textColor": "#FFFFFF",
                        }
                        if (
                            activity.activity_type in ["event", "meeting"]
                            and activity.is_all_day
                        ):
                            event["allDay"] = True
                        events.append(event)

                # Fetch UserAvailability events if selected
                if "unavailability" in selected_types:
                    unavailabilities = UserAvailability.objects.filter(
                        user=self.request.user
                    )
                    for unavailability in unavailabilities:
                        start_display = format_datetime_value(
                            unavailability.from_datetime, user=request.user
                        )
                        end_display = (
                            format_datetime_value(
                                unavailability.to_datetime, user=request.user
                            )
                            if unavailability.to_datetime
                            else None
                        )
                        event = {
                            "title": "User Unavailable",
                            "start": unavailability.from_datetime.isoformat(),
                            "end": (
                                unavailability.to_datetime.isoformat()
                                if unavailability.to_datetime
                                else None
                            ),
                            "start_display": start_display,
                            "end_display": end_display,
                            "calendarType": "unavailability",
                            "description": unavailability.reason
                            or "No reason provided",
                            "id": f"unavailability_{unavailability.id}",
                            "url": (
                                unavailability.update_mark_unavailability_url()
                                if unavailability.pk
                                else None
                            ),
                            "deleteUrl": (
                                unavailability.delete_mark_unavailability_url()
                                if unavailability.pk
                                else None
                            ),
                            "backgroundColor": "#F51414",
                            "borderColor": "#F51414",
                            "textColor": "#FFFFFF",
                        }
                        events.append(event)

            return JsonResponse({"status": "success", "events": events})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)


class MarkCompletedView(LoginRequiredMixin, View):
    """View to mark an activity as completed via AJAX."""

    def post(self, request, *args, **kwargs):
        """Handle AJAX POST request to mark activity as completed."""
        try:
            data = json.loads(request.body)
            event_id = data.get("event_id")
            new_status = data.get("status")

            if not event_id or not new_status:
                return JsonResponse(
                    {"status": "error", "message": "Missing event_id or status"},
                    status=400,
                )

            activity = Activity.objects.get(pk=event_id)

            if not request.user.has_perm("activity.change_own_activity"):
                return JsonResponse(
                    {
                        "status": "error",
                        "message": "Permission denied: You don't have permission to change activities",
                    },
                    status=403,
                )

            status_permission = get_user_field_permission(
                request.user, Activity, "status"
            )
            if status_permission != "readwrite":
                return JsonResponse(
                    {
                        "status": "error",
                        "message": "Permission denied: You don't have permission to change status",
                    },
                    status=403,
                )

            if new_status not in dict(Activity.STATUS_CHOICES):
                return JsonResponse(
                    {"status": "error", "message": "Invalid status"}, status=400
                )

            activity.status = new_status
            activity.save()

            messages.success(request, _("Marked as completed successfully."))
            return JsonResponse(
                {
                    "status": "success",
                }
            )

        except Activity.DoesNotExist:
            return JsonResponse(
                {"status": "error", "message": "Activity not found"}, status=404
            )
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)


@method_decorator(htmx_required, name="dispatch")
class UserAvailabilityFormView(LoginRequiredMixin, HorillaSingleFormView):
    """View to handle marking user unavailability via a form."""

    model = UserAvailability
    form_title = _("Mark Unavailability")
    modal_height = False
    hidden_fields = ["user", "company", "is_active"]
    full_width_fields = ["from_datetime", "to_datetime", "reason"]
    save_and_new = False

    @cached_property
    def form_url(self):
        """Generate the form URL based on whether it's an update or create action."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "horilla_calendar:update_mark_unavailability", kwargs={"pk": pk}
            )
        return reverse_lazy("horilla_calendar:mark_unavailability")

    def get_initial(self):
        """Set initial form data (company, user, optional start date/time from request)."""
        initial = super().get_initial()
        company = (
            getattr(_thread_local, "request", None).active_company
            if hasattr(_thread_local, "request")
            else self.request.user.company
        )
        initial["company"] = company
        initial["user"] = self.request.user
        initial["company"] = company
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if not pk:
            date_str = self.request.GET.get("start_date_time")
            if date_str:
                try:
                    clicked_datetime = datetime.datetime.fromisoformat(date_str)

                    clicked_date = clicked_datetime.date()
                    clicked_time = clicked_datetime.time()

                    start_datetime = timezone.make_aware(
                        datetime.datetime.combine(clicked_date, clicked_time)
                    )

                    end_datetime = start_datetime + datetime.timedelta(minutes=30)

                    initial["from_datetime"] = start_datetime
                    initial["to_datetime"] = end_datetime

                except ValueError:
                    initial["from_datetime"] = timezone.now()
                    initial["to_datetime"] = timezone.now()
            else:
                now = timezone.now()
                initial["from_datetime"] = now
                initial["to_datetime"] = now + datetime.timedelta(minutes=30)

        return initial

    def form_valid(self, form):
        """
        Handle form submission and save the meeting.
        """

        super().form_valid(form)
        return HttpResponse(
            "<script>$('#reloadMainContent').click();closeModal();</script>"
        )

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_calendar.delete_userunavailability"),
    name="dispatch",
)
class UserAvailabilityDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View to handle deletion of user unavailability records."""

    model = UserAvailability

    def get_post_delete_response(self):
        return HttpResponse(
            "<script>htmx.trigger('#reloadMainContent','click');</script>"
        )
