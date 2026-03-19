"""
Defines filters for the Campaign model, enabling search and exclusion of specific fields.
"""

# First-party / Horilla imports
from horilla_core.mixins import OwnerFiltersetMixin
from horilla_generics.filters import HorillaFilterSet

# Local imports
from .models import Campaign


class CampaignFilter(OwnerFiltersetMixin, HorillaFilterSet):
    """
    Campaign Filter
    """

    class Meta:
        """
        Meta class for CampaignFilter
        """

        model = Campaign
        fields = "__all__"
        exclude = ["additional_info"]
        search_fields = ["campaign_name"]
