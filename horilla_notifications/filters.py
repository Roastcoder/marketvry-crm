"""Filter classes for notification template models."""

from horilla_generics.filters import HorillaFilterSet

from .models import NotificationTemplate

# Define your notifications filters here


class NotificationTemplateFilter(HorillaFilterSet):
    """Filter set for HorillaMailTemplate model."""

    class Meta:
        """Meta class for HorillaMailTemplateFilter."""

        model = NotificationTemplate
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["title"]
