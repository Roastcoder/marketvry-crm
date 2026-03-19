"""Branding configuration utilities for Horilla."""

from importlib import import_module

from django.conf import settings
from django.utils.translation import gettext_lazy as _

DEFAULTS = {
    "TITLE": _("Marketvry"),
    "LOGIN_WELCOME_LINE": _("Welcome to Marketvry"),
    "LOGIN_TAG_LINE": _("Please sign in to access your dashboard"),
    "SIGNUP_TAG_LINE": _("Please sign up to access Marketvry"),
    "LOGO_PATH": "images/logo.png",
    "FAVICON_PATH": "favicon.ico",
    "PAGE_HEADER": _("Marketvry"),
}
