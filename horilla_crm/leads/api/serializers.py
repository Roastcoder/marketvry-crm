"""
Serializers for horilla_crm.leads models
"""

from rest_framework import serializers

from horilla_crm.leads.models import Lead, LeadStatus, ScoringCriterion, ScoringRule


class LeadSerializer(serializers.ModelSerializer):
    """Serializer for Lead model"""

    class Meta:
        """Meta options for LeadSerializer."""

        model = Lead
        fields = "__all__"


class LeadStatusSerializer(serializers.ModelSerializer):
    """Serializer for LeadStatus model"""

    class Meta:
        """Meta options for LeadStatusSerializer."""

        model = LeadStatus
        fields = "__all__"


class ScoringRuleSerializer(serializers.ModelSerializer):
    """Serializer for ScoringRule model"""

    class Meta:
        """Meta options for ScoringRuleSerializer."""

        model = ScoringRule
        fields = "__all__"


class ScoringCriterionSerializer(serializers.ModelSerializer):
    """Serializer for ScoringCriterion model"""

    class Meta:
        """Meta options for ScoringCriterionSerializer."""

        model = ScoringCriterion
        fields = "__all__"
