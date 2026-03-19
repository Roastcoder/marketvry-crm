"""Version information for the horilla_automations module."""

from horilla.utils.translation import gettext_lazy as _

__version__ = "1.1.1"
__module_name__ = "Automations"
__release_date__ = ""
__description__ = _(
    "Module for automating mail and notifications based on model events and conditions."
)
__icon__ = "assets/icons/automation.svg"

__1_1_1__ = _(
    "Minor compatibility improvements and internal stability updates"
    "to ensure seamless integration with the updated generics framework and platform enhancements."
)

__1_1_0__ = _(
    "Migrated from Django AppConfig to Horilla AppLauncher and replaced Django utilities"
    "with horilla.utils.decorators, horilla.utils.translation, and horilla.shortcuts where applicable."
)
