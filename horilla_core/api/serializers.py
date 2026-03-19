"""
Serializers for horilla_core models
"""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from horilla.auth.models import User
from horilla_core.models import (
    BusinessHour,
    Company,
    CustomerRole,
    Department,
    Holiday,
    HorillaAttachment,
    ImportHistory,
    PartnerRole,
    Role,
    TeamRole,
)


class CompanySerializer(serializers.ModelSerializer):
    """Serializer for Company model"""

    class Meta:
        """Meta class for CompanySerializer"""

        model = Company
        fields = "__all__"


class DepartmentSerializer(serializers.ModelSerializer):
    """Serializer for Department model"""

    class Meta:
        """Meta class for DepartmentSerializer"""

        model = Department
        fields = "__all__"


class RoleSerializer(serializers.ModelSerializer):
    """Serializer for Role model"""

    class Meta:
        """Meta class for RoleSerializer"""

        model = Role
        fields = "__all__"


class HorillaUserSerializer(serializers.ModelSerializer):
    """Serializer for HorillaUser model"""

    class Meta:
        """Meta class for HorillaUserSerializer"""

        model = User
        fields = "__all__"
        extra_kwargs = {"password": {"write_only": True}}

    def create(self, validated_data):
        """Create and return a user with the given validated data."""
        password = validated_data.get("password")
        if password:
            try:
                validate_password(password)
            except DjangoValidationError as e:
                raise serializers.ValidationError({"password": e.messages})
        user = User.objects.create_user(**validated_data)
        return user

    def update(self, instance, validated_data):
        """Update user; set password via set_password if provided."""
        if "password" in validated_data:
            password = validated_data.pop("password")
            try:
                validate_password(password, user=instance)
            except DjangoValidationError as e:
                raise serializers.ValidationError({"password": e.messages})
            instance.set_password(password)
        return super().update(instance, validated_data)


class BusinessHourSerializer(serializers.ModelSerializer):
    """Serializer for BusinessHour model"""

    class Meta:
        """Meta class for BusinessHourSerializer"""

        model = BusinessHour
        fields = "__all__"


class TeamRoleSerializer(serializers.ModelSerializer):
    """Serializer for TeamRole model"""

    class Meta:
        """Meta class for TeamRoleSerializer"""

        model = TeamRole
        fields = "__all__"


class CustomerRoleSerializer(serializers.ModelSerializer):
    """Serializer for CustomerRole model"""

    class Meta:
        """Meta class for CustomerRoleSerializer"""

        model = CustomerRole
        fields = "__all__"


class PartnerRoleSerializer(serializers.ModelSerializer):
    """Serializer for PartnerRole model"""

    class Meta:
        """Meta class for PartnerRoleSerializer"""

        model = PartnerRole
        fields = "__all__"


class ImportHistorySerializer(serializers.ModelSerializer):
    """Serializer for ImportHistory model"""

    class Meta:
        """Meta class for ImportHistorySerializer"""

        model = ImportHistory
        fields = "__all__"


class HorillaAttachmentSerializer(serializers.ModelSerializer):
    """Serializer for HorillaAttachment model"""

    class Meta:
        """Meta class for HorillaAttachmentSerializer"""

        model = HorillaAttachment
        fields = "__all__"


class HolidaySerializer(serializers.ModelSerializer):
    """Serializer for Holiday model"""

    class Meta:
        """Meta class for HolidaySerializer"""

        model = Holiday
        fields = "__all__"
