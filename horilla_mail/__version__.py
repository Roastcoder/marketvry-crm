"""Version information for the horilla_mail module."""

from horilla.utils.translation import gettext_lazy as _

__version__ = "1.1.1"
__module_name__ = "Mail"
__release_date__ = ""
__description__ = _(
    "Module for managing incoming and outgoing emails through mail servers and Outlook."
)
__icon__ = "assets/icons/icon1.svg"

__1_1_1__ = _(
    "Minor compatibility improvements and internal stability updates "
    "to align with the enhanced generics framework and visualization system."
)
__1_1_0__ = _(
    "Migrated from Django AppConfig to Horilla AppLauncher and and replaced"
    "Django utilities with horilla.utils.decorators, horilla.utils.translation, and horilla.shortcuts where applicable."
)
