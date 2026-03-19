"""
Version and metadata information for the horilla_keys module.
"""

from horilla.utils.translation import gettext_lazy as _

__version__ = "1.1.0"
__module_name__ = "Short Keys"
__release_date__ = ""
__description__ = _("Module providing customizable keyboard shortcuts.")
__icon__ = "horilla_keys/assets/icons/icon3.svg"

__1_1_0__ = _(
    "Migrated from Django AppConfig to Horilla AppLauncher and replaced Django"
    "utilities with horilla.utils.decorators, horilla.utils.translation, and horilla.shortcuts where applicable."
)
