"""Package metadata for the `horilla_reports` app."""

from horilla.utils.translation import gettext_lazy as _

__version__ = "1.2.0"
__module_name__ = "Reports"
__release_date__ = ""
__description__ = _(
    "Module for creating and customizing reports across all system modules."
)
__icon__ = "assets/icons/icon5.svg"

__1_2_0__ = _(
    "Added support for advanced chart types including Treemap, Area charts, "
    "Heatmaps, Sankey diagrams, and Radar charts. Improved compatibility with "
    "the new visualization and analytics framework."
)

__1_1_0__ = _(
    "Migrated from Django AppConfig to Horilla AppLauncher and and replaced"
    "Django utilities with horilla.utils.decorators, horilla.utils.translation,"
    "and horilla.shortcuts where applicable."
)
