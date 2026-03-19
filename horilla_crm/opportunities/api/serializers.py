"""
Serializers for horilla_crm.opportunities models
"""

from rest_framework import serializers

from horilla_core.api.serializers import HorillaUserSerializer
from horilla_crm.opportunities.models import (
    DefaultOpportunityMember,
    Opportunity,
    OpportunityStage,
    OpportunityTeam,
    OpportunityTeamMember,
)


class OpportunityStageSerializer(serializers.ModelSerializer):
    """Serializer for OpportunityStage model"""

    class Meta:
        """Meta options for OpportunityStageSerializer."""

        model = OpportunityStage
        fields = "__all__"


class OpportunitySerializer(serializers.ModelSerializer):
    """Serializer for Opportunity model"""

    owner_details = HorillaUserSerializer(source="owner", read_only=True)
    stage_details = OpportunityStageSerializer(source="stage", read_only=True)

    class Meta:
        """Meta options for OpportunitySerializer."""

        model = Opportunity
        fields = "__all__"


class OpportunityTeamSerializer(serializers.ModelSerializer):
    """Serializer for OpportunityTeam model"""

    owner_details = HorillaUserSerializer(source="owner", read_only=True)

    class Meta:
        """Meta options for OpportunityTeamSerializer."""

        model = OpportunityTeam
        fields = "__all__"


class OpportunityTeamMemberSerializer(serializers.ModelSerializer):
    """Serializer for OpportunityTeamMember model"""

    user_details = HorillaUserSerializer(source="user", read_only=True)
    opportunity_details = OpportunitySerializer(source="opportunity", read_only=True)

    class Meta:
        """Meta options for OpportunityTeamMemberSerializer."""

        model = OpportunityTeamMember
        fields = "__all__"


class DefaultOpportunityMemberSerializer(serializers.ModelSerializer):
    """Serializer for DefaultOpportunityMember model"""

    user_details = HorillaUserSerializer(source="user", read_only=True)
    team_details = OpportunityTeamSerializer(source="team", read_only=True)

    class Meta:
        """Meta options for DefaultOpportunityMemberSerializer."""

        model = DefaultOpportunityMember
        fields = "__all__"
