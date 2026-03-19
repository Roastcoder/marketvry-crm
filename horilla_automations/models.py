"""
Models for the horilla_automations app
"""

# Third-party imports (Django)
from django.conf import settings
from django.utils.html import format_html

from horilla.core.exceptions import ValidationError

# First-party imports (Horilla)
from horilla.db import models
from horilla.registry.limiters import limit_content_types
from horilla.registry.permission_registry import permission_exempt_model
from horilla.urls import reverse_lazy
from horilla.utils.choices import OPERATOR_CHOICES
from horilla.utils.translation import gettext_lazy as _
from horilla_core.models import HorillaContentType, HorillaCoreModel
from horilla_mail.models import HorillaMailConfiguration, HorillaMailTemplate
from horilla_notifications.models import NotificationTemplate

# Create your horilla_automations models here.
CONDITIONS = [
    ("equal", _("Equal (==)")),
    ("notequal", _("Not Equal (!=)")),
    ("lt", _("Less Than (<)")),
    ("gt", _("Greater Than (>)")),
    ("le", _("Less Than or Equal To (<=)")),
    ("ge", _("Greater Than or Equal To (>=)")),
    ("icontains", _("Contains")),
]


class HorillaAutomation(HorillaCoreModel):
    """
    MailAutoMation
    """

    choices = [
        ("on_create", "On Create"),
        ("on_update", "On Update"),
        ("on_create_or_update", "Both Create and Update"),
        ("on_delete", "On Delete"),
    ]
    SEND_OPTIONS = [
        ("mail", "Send as Mail"),
        ("notification", "Send as Notification"),
        ("both", "Send as Mail and Notification"),
    ]

    title = models.CharField(max_length=256, unique=True, verbose_name=_("Title"))
    method_title = models.CharField(
        max_length=100, editable=False, verbose_name=_("Method Title")
    )
    model = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        limit_choices_to=limit_content_types("automation_models"),
        verbose_name=_("Module"),
    )
    mail_to = models.TextField(
        verbose_name=_("Mail to/Notify to"),
        help_text=_(
            "Specify recipients for email/notifications. Supports:\n"
            "- Direct email: user@example.com\n"
            "- Self: 'self' (person who triggered)\n"
            "- Instance fields: 'instance.owner.email', 'instance.created_by', 'instance.owner'\n"
            "- Multiple: comma-separated (e.g., 'self, instance.owner.email, admin@example.com')\n\n"
            "For notifications: Use user fields directly (e.g., 'instance.owner') or email addresses.\n"
            "The system will find users by email if an email address is provided."
        ),
    )
    also_sent_to = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        verbose_name=_("Also Send to"),
    )

    mail_detail_choice = models.TextField(
        default="", editable=False, verbose_name=_("Mail Detail Choice")
    )
    trigger = models.CharField(
        max_length=20, choices=choices, verbose_name=_("Trigger")
    )
    mail_template = models.ForeignKey(
        HorillaMailTemplate,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_("Mail Template"),
    )
    notification_template = models.ForeignKey(
        NotificationTemplate,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_("Notification Template"),
    )
    mail_server = models.ForeignKey(
        HorillaMailConfiguration,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"mail_channel": "outgoing"},
        verbose_name=_("Outgoing Mail Server"),
        help_text=_(
            "Select the mail server to use for sending emails. If not selected, the primary mail server will be used."
        ),
    )
    delivery_channel = models.CharField(
        default="mail",
        max_length=50,
        choices=SEND_OPTIONS,
        verbose_name=_("Choose Delivery Channel"),
    )

    class Meta:
        """
        Meta class for HorillaAutomation model
        """

        verbose_name = _("Mail and Notification")
        verbose_name_plural = _("Mail and Notifications")

    def get_template(self):
        """
        Returns the template content based on the selected delivery channel.
        """
        templates = {
            "mail": self.mail_template,
            "notification": self.notification_template,
        }

        if self.delivery_channel in templates:
            return templates[self.delivery_channel]

        return format_html(
            "Mail Template: {}<br>Notification Template: {}",
            self.mail_template,
            self.notification_template,
        )

    def clean(self):
        """Validate template fields based on delivery_channel."""
        super().clean()
        if (
            self.delivery_channel == "notification"
            and not self.notification_template_id
        ):
            raise ValidationError(
                {
                    "notification_template": _(
                        "Notification template is required when delivery channel is "
                        "'Send as Notification'."
                    )
                }
            )
        if self.delivery_channel == "mail":
            if not self.mail_template_id:
                raise ValidationError(
                    {
                        "mail_template": _(
                            "Mail template is required when delivery channel is "
                            "'Send as Mail'."
                        )
                    }
                )
            if not self.mail_server_id:
                raise ValidationError(
                    {
                        "mail_server": _(
                            "Outgoing mail server is required when delivery channel is "
                            "'Send as Mail'."
                        )
                    }
                )
        if self.delivery_channel == "both":
            if not self.mail_template_id:
                raise ValidationError(
                    {
                        "mail_template": _(
                            "Mail template is required when delivery channel is "
                            "'Send as Mail and Notification'."
                        )
                    }
                )
            if not self.notification_template_id:
                raise ValidationError(
                    {
                        "notification_template": _(
                            "Notification template is required when delivery channel is "
                            "'Send as Mail and Notification'."
                        )
                    }
                )
            if not self.mail_server_id:
                raise ValidationError(
                    {
                        "mail_server": _(
                            "Outgoing mail server is required when delivery channel is "
                            "'Send as Mail and Notification'."
                        )
                    }
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        if not self.pk:
            self.method_title = self.title.replace(" ", "_").lower()
        return super().save(*args, **kwargs)

    def get_edit_url(self):
        """
        Get the URL to edit this automation.
        """
        return reverse_lazy(
            "horilla_automations:automation_update_view", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """
        Get the URL to delete this automation.
        """
        return reverse_lazy(
            "horilla_automations:automation_delete_view", kwargs={"pk": self.pk}
        )

    def __str__(self) -> str:
        return str(self.title)


@permission_exempt_model
class AutomationCondition(HorillaCoreModel):
    """
    Defines filtering conditions for automations
    """

    automation = models.ForeignKey(
        HorillaAutomation,
        on_delete=models.CASCADE,
        related_name="conditions",
        verbose_name=_("Automation"),
    )

    field = models.CharField(max_length=100, verbose_name=_("Field Name"))
    operator = models.CharField(
        max_length=50,
        choices=OPERATOR_CHOICES,
        verbose_name=_("Operator"),
    )

    value = models.CharField(max_length=255, blank=True, verbose_name=_("Value"))

    logical_operator = models.CharField(
        max_length=3,
        choices=[("and", _("AND")), ("or", _("OR"))],
        default="and",
        verbose_name=_("Logical Operator"),
    )

    order = models.PositiveIntegerField(default=0, verbose_name=_("Order"))

    class Meta:
        """Meta options for AutomationCondition model."""

        verbose_name = _("Automation Condition")
        verbose_name_plural = _("Automation Conditions")
        ordering = ["order", "created_at"]

    def __str__(self):
        return f"{self.automation.title} - {self.field} {self.operator} {self.value}"
