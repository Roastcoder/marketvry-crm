"""Date/time template filters using user/company format and timezone."""

from datetime import datetime

from dateutil import parser as dateutil_parser
from django.utils import timezone

from ._registry import register
from ._shared import _get_request_user_company, format_datetime_value


@register.filter
def user_datetime_format(value):
    """
    Format a date, datetime, or time using the request user's format,
    falling back to company format. Use in templates: {{ value|user_datetime_format }}

    Returns formatted string for date/datetime/time; passes through other values.
    """
    _, user, company = _get_request_user_company()
    result = format_datetime_value(
        value, user=user, company=company, convert_timezone=True
    )
    return result if result is not None else value


@register.filter
def user_datetime_format_display(value):
    """
    Same as user_datetime_format but also accepts pre-formatted date/datetime
    strings (e.g. from auditlog changes_display_dict). Parses the string and
    re-formats with the user's format. Use in history "updated" section so
    dates match the rest of the page: {{ value|user_datetime_format_display }}
    """
    _, user, company = _get_request_user_company()
    result = format_datetime_value(
        value, user=user, company=company, convert_timezone=True
    )
    if result is not None:
        return result
    # Parse pre-formatted date/datetime strings and re-format with user format
    if (
        isinstance(value, str)
        and value
        and value not in ("--", "None", "none")
        and dateutil_parser
    ):
        try:
            parsed = dateutil_parser.parse(value)
            if isinstance(parsed, datetime) and timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_default_timezone())
            result = format_datetime_value(
                parsed, user=user, company=company, convert_timezone=True
            )
            if result is not None:
                return result
        except (ValueError, TypeError, OverflowError):
            pass
    return value
