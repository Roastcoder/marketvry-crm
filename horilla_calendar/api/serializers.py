"""
Serializers for Horilla Calendar models
"""

from rest_framework import serializers

from horilla_calendar.models import UserAvailability, UserCalendarPreference
from horilla_core.api.serializers import HorillaUserSerializer


class UserCalendarPreferenceSerializer(serializers.ModelSerializer):
    """Serializer for UserCalendarPreference model"""

    user_details = HorillaUserSerializer(source="user", read_only=True)

    class Meta:
        """Meta class for UserCalendarPreferenceSerializer"""

        model = UserCalendarPreference
        fields = "__all__"


class UserAvailabilitySerializer(serializers.ModelSerializer):
    """Serializer for UserAvailability model"""

    user_details = HorillaUserSerializer(source="user", read_only=True)

    class Meta:
        """Meta class for UserAvailabilitySerializer"""

        model = UserAvailability
        fields = "__all__"
