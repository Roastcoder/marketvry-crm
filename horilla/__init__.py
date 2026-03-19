"""
Horilla package initialization.

Expose the project's Celery application as `celery_app` for external use.
"""

from .horilla_celery import app as celery_app

__all__ = [
    "celery_app",
]
