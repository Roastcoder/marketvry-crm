"""Queryset limiters for registry-backed feature configuration."""

# Third-party imports (Django)
from django.db import models

# First party imports (Horilla)
from horilla.registry.feature import FEATURE_REGISTRY


class ContentTypeLimiter:
    """
    Callable that limits ContentType choices based on FEATURE_REGISTRY key.
    Implements deconstruct() so Django can serialize it in migration files.
    """

    def __init__(self, feature_key):
        self.feature_key = feature_key

    def __call__(self):
        models_list = FEATURE_REGISTRY.get(self.feature_key, [])
        includable_models = [model._meta.model_name.lower() for model in models_list]
        return models.Q(model__in=includable_models)

    def deconstruct(self):
        """Return (path, args, kwargs) for Django migration serialization."""
        return (
            "horilla.registry.limiters.ContentTypeLimiter",
            [self.feature_key],
            {},
        )


def limit_content_types(feature_key):
    """
    Returns a callable that limits ContentType choices
    based on FEATURE_REGISTRY key.
    """
    return ContentTypeLimiter(feature_key)
