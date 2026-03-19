"""Module containing package metadata used by Horilla (version, name, icons)."""

from django.utils.translation import gettext_lazy as _

__version__ = "1.5.0"
__module_name__ = _("Core System")
__release_date__ = ""
__description__ = _(
    "Core system providing authentication, configuration, utilities, and platform-level services."
)
__icon__ = "assets/icons/logo.png"


__1_5_0__ = _(
    "Improved global search model registry loading, standardized error handling "
    "with dedicated 403, 404, 405, and 500 templates, strengthened authentication "
    "flow using Django authenticate(), and applied multiple security and "
    "stability improvements across internal views."
)


__1_4_0__ = _(
    "Introduced the Horilla AppLauncher system for dynamic application "
    "registration. Added horilla.shortcuts, horilla.urls, and horilla.utils "
    "utilities. Refactored project URL handling and improved internal "
    "framework architecture for modular applications."
)


__1_2_0__ = _(
    "Improved system configuration handling, strengthened dashboard layout "
    "validation, enhanced filter processing reliability, and added multiple "
    "defensive validation improvements across core components."
)


__1_1_0__ = _(
    "Added an 'All Companies' option to the company dropdown, allowing users "
    "to view data irrespective of company selection."
)
