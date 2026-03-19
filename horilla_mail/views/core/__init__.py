"""
Views for Horilla Mail app.

This package provides mail form, recipients, preview, draft, delete and schedule views.
Submodules: base, form, recipients, preview_draft, delete_schedule.
"""

from horilla_mail.views.core.base import extract_inline_images_with_cid, parse_email_pills_context
from horilla_mail.views.core.schedule import (
    HorillaMailtDeleteView,
    ScheduleMailModallView,
    ScheduleMailView,
)
from horilla_mail.views.core.form import HorillaMailFormView
from horilla_mail.views.core.preview_draft import (
    CheckDraftChangesView,
    DiscardDraftView,
    HorillaMailPreviewView,
    SaveDraftView,
)
from horilla_mail.views.core.recipients import (
    AddEmailView,
    EmailSuggestionView,
    HorillaMailFieldSelectionView,
    RemoveEmailView,
)

__all__ = [
    "parse_email_pills_context",
    "extract_inline_images_with_cid",
    "HorillaMailFormView",
    "AddEmailView",
    "RemoveEmailView",
    "EmailSuggestionView",
    "HorillaMailFieldSelectionView",
    "HorillaMailPreviewView",
    "CheckDraftChangesView",
    "SaveDraftView",
    "DiscardDraftView",
    "HorillaMailtDeleteView",
    "ScheduleMailView",
    "ScheduleMailModallView",
]
