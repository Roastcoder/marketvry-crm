"""CRM module version information."""

from horilla.utils.translation import gettext_lazy as _

__version__ = "1.3.0"
__module_name__ = "CRM"
__release_date__ = "13 March 2026"
__description__ = _("CRM module for managing leads, contacts, and opportunities.")
__icon__ = "assets/icons/icon2.svg"

__1_3_0__ = _(
    "Introduced advanced CRM visualization capabilities including chart views, "
    "timeline (Gantt-style) views, split layout navigation, and card-based record "
    "views. Improved pipeline data exploration and navigation across Leads, "
    "Accounts, Campaigns, Contacts, and Opportunities."
)

__1_2_0__ = _(
    "Enabled advanced quick filters, improved column selector behavior, "
    "refined CRM list view consistency, and enhanced filtering reliability "
    "across Leads, Accounts, Contacts, Campaigns, and Opportunities."
)

__1_1_0__ = _(
    "Migrated CRM sub-apps to Horilla AppLauncher and replaced Django utilities "
    "with horilla.utils.decorators, horilla.utils.translation, and horilla.shortcuts "
    "where applicable."
)
