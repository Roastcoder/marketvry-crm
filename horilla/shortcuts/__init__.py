"""Horilla shortcuts: redirect, render, and get_object_or_404."""

from django.shortcuts import redirect, render

from .query_helpers import get_object_or_404

__all__ = ["redirect", "render", "get_object_or_404"]
