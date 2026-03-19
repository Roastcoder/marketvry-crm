"""Helper functions for horilla_dashboard views."""

# Standard library imports
import logging

# Third-party imports (Django)
from django.db.models import Q

logger = logging.getLogger(__name__)


def get_queryset_for_module(user, model):
    """
    Returns queryset for a given model based on user permissions.
    Uses model.OWNER_FIELDS if available.
    """
    app_label = model._meta.app_label
    model_name = model._meta.model_name

    if user.has_perm(f"{app_label}.view_{model_name}"):
        return model.objects.all()

    if user.has_perm(f"{app_label}.view_own_{model_name}"):
        owner_fields = getattr(model, "OWNER_FIELDS", [])
        if not owner_fields:
            return model.objects.none()

        q_filter = Q()
        for field in owner_fields:
            q_filter |= Q(**{field: user})
        return model.objects.filter(q_filter)

    return model.objects.none()
