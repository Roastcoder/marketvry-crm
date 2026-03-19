"""Helper functions for LoginHistory model display and formatting.

This module provides utility functions that are attached to the LoginHistory model
to enhance its display capabilities. These functions handle:
- User status display (Login/Logout)
- User agent string truncation
- Date-time formatting
- Login/logout icon rendering
"""

from django.utils.html import format_html
from django.utils.timezone import localtime
from login_history.models import LoginHistory


def user_status(self):
    """Return 'Login' or 'Logout' based on is_logged_in status."""
    if self.is_logged_in is True:
        return "Login"
    return "Logout"


def short_user_agent(self):
    """
    Returns only the first part of the user agent (up to the first closing parenthesis).
    """
    if self.user_agent:
        end = self.user_agent.find(")") + 1  # Find first closing bracket
        if end > 0:
            return self.user_agent[:end]
    return self.user_agent


def formatted_datetime(self):
    """Return formatted local date-time string."""
    local_dt = localtime(self.date_time)
    return (
        local_dt.strftime("%d %b %Y, %I:%M %p")
        .lower()
        .replace("am", "a.m.")
        .replace("pm", "p.m.")
    )


def is_login_icon(self):
    """Return HTML for login/logout icon based on is_logged_in status."""
    if self.is_logged_in:
        # Green check icon
        return format_html(
            '<span class="flex justify-center items-center inline-block text-green-600">'
            '<i class="{}"></i></span>',
            "fas fa-check-circle fa-lg",
        )
    # Red cross icon
    return format_html(
        '<span class=" flex justify-center items-center inline-block text-red-600">'
        '<i class="{}"></i></span>',
        "fas fa-times-circle fa-lg",
    )


LoginHistory.user_status = user_status
LoginHistory.short_user_agent = short_user_agent
LoginHistory.formatted_datetime = formatted_datetime
LoginHistory.is_login_icon = is_login_icon
LoginHistory.PROPERTY_LABELS = {
    "user_status": "Status",
    "short_user_agent": "Browser",
    "formatted_datetime": "Login Time",
    "is_login_icon": "Is Active",
}
