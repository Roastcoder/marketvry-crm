"""
Serializers for horilla_activity models
"""

from rest_framework import serializers

from horilla_activity.models import Activity
from horilla_core.api.serializers import HorillaUserSerializer


class ActivitySerializer(serializers.ModelSerializer):
    """Serializer for Activity model"""

    owner_details = HorillaUserSerializer(source="owner", read_only=True)
    meeting_host_details = HorillaUserSerializer(source="meeting_host", read_only=True)
    assigned_to_details = HorillaUserSerializer(
        source="assigned_to", many=True, read_only=True
    )
    participants_details = HorillaUserSerializer(
        source="participants", many=True, read_only=True
    )

    class Meta:
        """Meta class for ActivitySerializer"""

        model = Activity
        fields = "__all__"
