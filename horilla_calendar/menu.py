"""
This module registers Floating, Settings, My Settings, and Main Section menus
for the Horilla Calendar app
"""

from horilla.menu import main_section_menu, sub_section_menu

# First party / Horilla imports
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _


@main_section_menu.register
class AnalyticsSection:
    """
    Registers the Schedule section in the main sidebar.
    """

    section = "schedule"
    name = _("Schedule")
    icon = "/assets/icons/schedule.svg"
    position = 4


@sub_section_menu.register
class CalendarSubSection:
    """
    Registers the calendar  menu to sub section in the main sidebar.
    """

    section = "schedule"
    verbose_name = _("Calendar")
    icon = "assets/icons/calendar.svg"
    url = reverse_lazy("horilla_calendar:calendar_view")
    app_label = "horilla_calendar"
    position = 1
    attrs = {
        "hx-boost": "true",
        "hx-target": "#mainContent",
        "hx-select": "#mainContent",
        "hx-swap": "outerHTML",
    }
