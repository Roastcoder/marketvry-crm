"""
Lightweight URL helper utilities for Horilla.

This module is safe to import from models and other early-loaded modules,
because it only re-exports primitives from Django's URL utilities and does
not import the project root URL configuration or any third-party URLconfs.
"""

from django.urls import (
    clear_url_caches,
    get_resolver,
    get_urlconf,
    include,
    path,
    re_path,
    resolve,
    reverse,
    reverse_lazy,
    Resolver404,
)

__all__ = [
    "path",
    "re_path",
    "include",
    "reverse",
    "reverse_lazy",
    "resolve",
    "Resolver404",
    "get_resolver",
    "get_urlconf",
    "clear_url_caches",
]
