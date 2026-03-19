"""
Horilla database model extensions.

This package currently exposes a custom ``GenericForeignKey`` that wraps
the Django contenttypes field with additional behavior.
"""

from django.db.models import *  # noqa
from django.db import models as _django_models

from horilla.db.models.fields import GenericForeignKey

__all__ = list(_django_models.__all__) + ["GenericForeignKey"]
