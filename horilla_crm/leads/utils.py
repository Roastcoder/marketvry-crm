"""Utility functions for leads module."""

from horilla_crm.leads.models import ScoringRule


def compute_score(instance):
    """
    Compute the score for a given instance (Lead, Opportunity, Account, or Contact)
    based on active ScoringRules for the instance's module.

    Args:
        instance: A model instance (e.g., Lead, Opportunity) to score.

    Returns:
        int: The computed score (sum of points from matching criteria).

    Logic:
        - Filters active rules for the instance's module (e.g., 'lead').
        - For each rule, evaluates criteria in order.
        - If a criterion's conditions are met, adds/subtracts points based on operation_type.
        - Returns the total score.
    """
    module = instance._meta.model_name  # e.g., 'lead', 'opportunity'
    rules = ScoringRule.objects.filter(module=module, is_active=True)
    score = 0

    for rule in rules:
        for criterion in rule.criteria.all().order_by("order"):
            if criterion.evaluate_conditions(instance):
                points = criterion.points
                if criterion.operation_type == "sub":
                    points = -points
                score += points

    return score
