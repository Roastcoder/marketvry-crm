"""Template tags for displaying field values and currency."""

from horilla_core.models import MultipleCurrency
from horilla_core.utils import get_currency_display_value

from ._registry import register
from ._shared import _get_request_user_company, format_datetime_value


@register.simple_tag
def display_field_value(obj, field_name, user):
    """
    Template tag to display field value with automatic currency formatting,
    datetime timezone conversion, and custom formatting

    Usage in template:
    {% display_field_value obj field_name request.user %}

    Works automatically if model has CURRENCY_FIELDS attribute
    Handles datetime fields with user's timezone and format preferences
    """
    if (
        hasattr(obj.__class__, "CURRENCY_FIELDS")
        and field_name in obj.__class__.CURRENCY_FIELDS
    ):
        return get_currency_display_value(obj, field_name, user)

    if hasattr(obj, "get_field_display"):
        return obj.get_field_display(field_name, user)

    value = getattr(obj, field_name, None)

    if value is None:
        return ""

    _, _, company = _get_request_user_company()

    formatted = format_datetime_value(
        value, user=user, company=company, convert_timezone=True
    )
    if formatted is not None:
        return formatted

    if hasattr(value, "all"):
        related_objects = value.all()
        if related_objects.exists():
            return ", ".join(str(item) for item in related_objects)
        return ""

    try:
        field = obj._meta.get_field(field_name)
        if hasattr(field, "choices") and field.choices:
            return dict(field.choices).get(value, value)
    except Exception:
        pass

    if hasattr(value, "__str__"):
        return str(value)

    return value


@register.filter
def format_currency(value, user):
    """Template filter for currency formatting"""
    if not value:
        return ""

    user_currency = MultipleCurrency.get_user_currency(user)
    if user_currency:
        return user_currency.display_with_symbol(value)

    return str(value)
