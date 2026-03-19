"""Miscellaneous template tags."""

from horilla.auth.models import User

from ._registry import register


@register.simple_tag
def get_user_model_meta():
    """
    Get the User model metadata
    Returns: dict with app_label, model_name, and model_name_original
    """
    return {
        "app_label": User._meta.app_label,
        "model_name": User._meta.model_name,
        "model_class_name": User.__name__,
    }
