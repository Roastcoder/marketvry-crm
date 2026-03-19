"""
Horilla HTTP utilities.

Provides safe redirect and refresh response classes for use with Django
and HTMX (HX-* headers).
"""

from django.http import (
    Http404,
    QueryDict,
    HttpResponse,
    JsonResponse,
    FileResponse,
    HttpResponseRedirect,
    HttpResponseNotFound,
    HttpResponseNotAllowed,
    HttpResponseBadRequest,
)

from .url_safety import safe_url
from .response import HttpNotFound, RedirectResponse, RefreshResponse

__all__ = [
    "safe_url",
    "Http404",
    "QueryDict",
    "HttpNotFound",
    "HttpResponse",
    "JsonResponse",
    "FileResponse",
    "HttpResponseRedirect",
    "HttpResponseNotFound",
    "HttpResponseNotAllowed",
    "HttpResponseBadRequest",
    "RedirectResponse",
    "RefreshResponse",
]
