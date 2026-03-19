"""Convenience module for accessing the project's user model."""

from django.contrib.auth import get_user_model

User = get_user_model()
