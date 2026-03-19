"""
Filters for the horilla_automations app
"""

from horilla_automations.models import HorillaAutomation
from horilla_generics.filters import HorillaFilterSet

# Define your horilla_automations filters here


class HorillaAutomationFilter(HorillaFilterSet):
    """Filter set for HorillaMailConfiguration model."""

    class Meta:
        """Meta class for HorillaMailServerFilter."""

        model = HorillaAutomation
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["title"]
