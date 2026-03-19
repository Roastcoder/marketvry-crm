"""
Horilla translation - re-exports django.utils.translation for consistent imports.

Use: from horilla.utils.translation import gettext_lazy as _
     from horilla.utils.translation import gettext, get_language, ...
"""

from django.utils.translation import (
    activate,
    deactivate,
    get_language,
    get_language_bidi,
    get_language_info,
    gettext,
    gettext_lazy,
    ngettext,
    ngettext_lazy,
    npgettext,
    npgettext_lazy,
    override,
    pgettext,
    pgettext_lazy,
)

__all__ = [
    "activate",
    "deactivate",
    "get_language",
    "get_language_bidi",
    "get_language_info",
    "gettext",
    "gettext_lazy",
    "ngettext",
    "ngettext_lazy",
    "npgettext",
    "npgettext_lazy",
    "override",
    "pgettext",
    "pgettext_lazy",
]
