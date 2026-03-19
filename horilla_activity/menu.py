"""
This module registers Floating, Settings, My Settings, and Main Section menus
for the Horilla  Activities app
"""

# Third party imports (Django)

from horilla.menu import sub_section_menu

# First party / Horilla imports
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _


@sub_section_menu.register
class ActivitySubSection:
    """
    Registers the activity menu to sub section in the main sidebar.
    """

    section = "schedule"
    verbose_name = _("Activities")
    icon = "assets/icons/activity.svg"
    url = reverse_lazy("horilla_activity:activity_view")
    app_label = "horilla_activity"
    position = 2
    attrs = {
        "hx-boost": "true",
        "hx-target": "#mainContent",
        "hx-select": "#mainContent",
        "hx-swap": "outerHTML",
    }
