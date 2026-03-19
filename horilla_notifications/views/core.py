"""Views for handling notification-related operations."""

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.formats import date_format
from django.views import View

# First-party / Horilla imports
from horilla.db import models
from horilla.http import HttpResponse
from horilla.shortcuts import render
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _
from horilla_notifications.models import Notification


def _get_object_display_fields(obj, max_fields=12):
    """
    Build a list of (label, display_value) for an object's concrete fields.
    Used to show related object details in the notification popup when no URL is provided.
    """
    if obj is None:
        return []
    result = []
    excluded = {
        "id",
        "pk",
        "history",
        "additional_info",
        "is_active",
        "updated_at",
        "created_at",
    }
    for field in obj._meta.fields:
        if field.name in excluded:
            continue
        if getattr(field, "remote_field", None) and field.remote_field:
            continue
        try:
            value = getattr(obj, field.name, None)
            if value is None:
                display = ""
            elif isinstance(value, models.Model):
                display = str(value)
            elif hasattr(value, "strftime"):
                display = date_format(value, use_l10n=True) if value else ""
            elif isinstance(value, bool):
                display = _("Yes") if value else _("No")
            else:
                display = str(value)
            result.append((getattr(field, "verbose_name", field.name), display))
        except Exception:
            continue
        if len(result) >= max_fields:
            break
    return result


class MarkNotificationReadView(LoginRequiredMixin, View):
    """View to mark a single notification as read."""

    def post(self, request, pk, *args, **kwargs):
        """
        Mark a specific notification as read.

        Args:
            request: The HTTP request object.
            pk: Primary key of the notification to mark as read.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            HttpResponse: HTTP 200 response on success.
        """
        try:
            notif = Notification.objects.get(pk=pk, user=request.user)
            notif.read = True
            notif.save()
        except Notification.DoesNotExist:
            pass
        return HttpResponse("", status=200)


class MarkAllNotificationsReadView(LoginRequiredMixin, View):
    """View to mark all notifications as read for the current user."""

    def post(self, request, *args, **kwargs):
        """
        Mark all unread notifications as read for the current user.

        Args:
            request: The HTTP request object.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            HttpResponse: Rendered notification list template.
        """
        Notification.objects.filter(user=request.user, read=False).update(read=True)
        messages.success(request, "All notifications marked as read.")
        unread_notifications = Notification.objects.filter(
            user=request.user, read=False
        )
        return render(
            request,
            "notification_list.html",
            {
                "unread_notifications": unread_notifications,
            },
        )


class DeleteNotification(LoginRequiredMixin, View):
    """View to delete a single notification."""

    def post(self, request, pk, *args, **kwargs):
        """
        Delete a specific notification.

        Args:
            request: The HTTP request object.
            pk: Primary key of the notification to delete.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            HttpResponse: HTTP 200 response on success.
        """
        try:
            notif = Notification.objects.get(pk=pk, user=request.user)
            notif.delete()
        except Notification.DoesNotExist:
            pass
        messages.success(request, "Notification Deleted.")
        response = HttpResponse(status=200)
        return response


class DeleteAllNotification(LoginRequiredMixin, View):
    """View to delete all notifications for the current user."""

    def post(self, request, *args, **kwargs):
        """
        Delete all notifications for the current user.

        Args:
            request: The HTTP request object.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            HttpResponse: Rendered sidebar list template.
        """
        Notification.objects.filter(user=request.user).delete()
        messages.success(request, f"All notifications cleared.")
        return render(request, "sidebar_list.html", {"request": request})


@method_decorator(htmx_required, name="dispatch")
class OpenNotificationView(LoginRequiredMixin, View):
    """View to open a notification: redirect to URL if present, else show detail popup."""

    def get(self, request, pk, *args, **kwargs):
        """
        Mark a notification as read. If it has a URL, redirect. Otherwise show a
        detail popup with the related object's details (or notification message only).
        """
        try:
            notif = Notification.objects.get(pk=pk, user=request.user)
            notif.read = True
            notif.save()

            url = (notif.url or "").strip()
            response = HttpResponse()
            response["HX-Redirect"] = url
            return response

        except Notification.DoesNotExist:
            return render(request, "403.html", status=404)
