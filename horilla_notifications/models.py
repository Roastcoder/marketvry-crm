"""
model for horilla notifications
"""

# Third party imports (Django)
from django.conf import settings

from horilla.core.exceptions import ValidationError

# First-party (Horilla)
from horilla.db import models
from horilla.registry.limiters import limit_content_types
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# First-party / Horilla apps
from horilla_core.models import HorillaContentType, HorillaCoreModel
from horilla_utils.methods import has_xss


class Notification(models.Model):
    """
    Model representing a notification for a user.

    Notifications are messages sent to users, typically triggered by system
    events or actions from other users. Each notification can be marked as
    read and may include a URL for navigation.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    message = models.TextField()
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_notifications",
    )
    url = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)
    # Optional link to the related object (e.g. department, lead) for detail popup when url is missing
    content_type = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notification_related_objects",
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    related_object = models.GenericForeignKey("content_type", "object_id")

    def __str__(self):
        return f"Notification for {self.user.username}: {self.message}"

    def clean(self):
        """Validate model fields for XSS at model level (works for admin, forms, and API)."""
        errors = {}

        if self.message and has_xss(self.message):
            errors["message"] = _(
                "Message contains potentially dangerous content (XSS detected). "
                "Please remove any scripts or malicious code."
            )

        if self.url and has_xss(self.url):
            errors["url"] = _(
                "URL contains potentially dangerous content (XSS detected). "
                "Please remove any scripts or malicious code."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """Override save to ensure clean() is called for validation."""
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        """Meta options for the Notification model."""

        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")
        ordering = ["-created_at"]


class NotificationTemplate(HorillaCoreModel):
    """
    Model representing a notification template.
    """

    title = models.CharField(max_length=100, verbose_name=_("Template Title"))
    message = models.TextField(verbose_name=_("Message"))
    content_type = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        limit_choices_to=limit_content_types("notification_template_models"),
        verbose_name=_("Related Model"),
    )

    def __str__(self) -> str:
        return f"{self.title}"

    class Meta:
        """Meta options for the mail template model."""

        verbose_name = _("Notification Template")
        verbose_name_plural = _("Notification Templates")
        unique_together = ["title", "company"]

    def get_related_model(self):
        """Return the related model's verbose name."""
        if self.content_type:
            return self.content_type.model_class()._meta.verbose_name.title()
        return "General"

    def get_edit_url(self):
        """Get the URL to edit this notification template."""
        return reverse_lazy(
            "horilla_notifications:notification_template_update_view",
            kwargs={"pk": self.pk},
        )

    def get_delete_url(self):
        """Get the URL to delete this notification template."""
        return reverse_lazy(
            "horilla_notifications:notification_template_delete_view",
            kwargs={"pk": self.pk},
        )

    def get_detail_view_url(self):
        """Get the URL to view this notification template."""
        return reverse_lazy(
            "horilla_notifications:notification_template_detail_view",
            kwargs={"pk": self.pk},
        )
