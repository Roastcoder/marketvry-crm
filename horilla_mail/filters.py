"""Filter classes for horilla_mail models."""

from horilla_generics.filters import HorillaFilterSet
from horilla_mail.models import HorillaMailConfiguration, HorillaMailTemplate

# Define your horilla_mail filters here


class HorillaMailServerFilter(HorillaFilterSet):
    """Filter set for HorillaMailConfiguration model."""

    class Meta:
        """Meta class for HorillaMailServerFilter."""

        model = HorillaMailConfiguration
        fields = "__all__"
        exclude = ["additional_info", "token"]
        search_fields = ["host", "username"]


class HorillaMailTemplateFilter(HorillaFilterSet):
    """Filter set for HorillaMailTemplate model."""

    class Meta:
        """Meta class for HorillaMailTemplateFilter."""

        model = HorillaMailTemplate
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["title"]
