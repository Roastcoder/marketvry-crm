"""
Version information utilities for Horilla modules.

This module provides functions to retrieve and collect version information
from installed Horilla modules, including version numbers, descriptions,
and icons.
"""

from importlib import import_module

from django.conf import settings

from horilla import __version__ as horilla_version


def get_module_version_info(module_name):
    """Return module version info as a dict: {name, version, description}."""
    try:
        mod = import_module(f"{module_name}.__version__")

        return {
            "name": getattr(mod, "__module_name__", module_name),
            "version": getattr(mod, "__version__", "Unknown"),
            "description": getattr(mod, "__description__", ""),
            "icon": getattr(mod, "__icon__", ""),
        }

    except ModuleNotFoundError:
        return None


def collect_all_versions():
    """Collect version info for all top-level Horilla modules."""

    versions = [
        {
            "name": horilla_version.__module_name__,
            "version": horilla_version.__version__,
            "description": horilla_version.__description__,
            "icon": getattr(horilla_version, "__icon__", ""),
        }
    ]

    seen = set()

    for app in settings.INSTALLED_APPS:
        top_level = app.split(".")[0]

        if top_level not in seen:
            info = get_module_version_info(top_level)

            if info:
                versions.append(info)

            seen.add(top_level)

    return {
        "module_versions": versions,
    }
