"""
Version and metadata for the horilla_calendar app.

Contains the module's version string and descriptive metadata used in the
application registry and UI.
"""

from horilla.utils.translation import gettext_lazy as _

__version__ = "1.1.1"
__module_name__ = "Calendar"
__release_date__ = ""
__description__ = _("Module for managing calendar events and schedules.")
__icon__ = "assets/icons/calendar-red.svg"

__1_1_1__ = _(
    "Compatibility updates and minor internal improvements to align with "
    "platform architecture and generics framework updates."
)

__1_1_0__ = _(
    "Migrated from Django AppConfig to Horilla AppLauncher and replaced Django utilities"
    "with horilla.utils.decorators, horilla.utils.translation, and horilla.shortcuts where applicable."
)
