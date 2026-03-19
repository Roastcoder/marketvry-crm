"""
Horilla Decorator utilities.
"""

from django.utils.decorators import method_decorator

from .wrapper import (
    permission_required_or_denied,
    permission_required,
    htmx_required,
    db_initialization,
)

__all__ = [
    "method_decorator",
    "permission_required_or_denied",
    "permission_required",
    "htmx_required",
    "db_initialization",
]
