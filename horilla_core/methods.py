"""
core helper methods.
"""

from horilla.registry.feature import FEATURE_CONFIG, FEATURE_REGISTRY


def get_template_reverse_models():
    """
    Return the list of models allowed to appear as reverse relations in the
    Insert field modal. If the feature is not registered, returns None (meaning
    show all reverse relations). If registered, returns the list from the
    registry (may be empty).
    """
    if "template_reverse" not in FEATURE_CONFIG:
        return None
    registry_key = FEATURE_CONFIG["template_reverse"]
    return FEATURE_REGISTRY.get(registry_key, [])
