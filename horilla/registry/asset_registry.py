"""
JavaScript and HTML injection registry for Django apps.

This module exposes a lightweight registry that lets Django apps
dynamically register:

- Static JavaScript file paths, which are later included from the
  base template using ``get_registered_js()``.
- HTML template fragments that are injected into well-defined layout
  slots (``head_start``, ``head_end``, ``body_start``, ``body_end``)
  in a deterministic, priority-based order.
"""

# Global list to store registered JavaScript file paths
from collections import defaultdict
from typing import Dict, List

REGISTERED_JS_FILES = []
REGISTERED_HTML_BLOCKS: Dict[str, List[str]] = defaultdict(list)

# (template_path, slot, page) -> priority
REGISTERED_HTML_PRIORITY = {}

# slot -> list of (template_path, page)
REGISTERED_HTML_BLOCKS = defaultdict(list)

# Allowed inject slots in index.html
INJECT_ALLOWED_SLOTS = {
    "head_start",
    "head_end",
    "body_start",
    "body_end",
}


def register_js(static_paths):
    """
    Register one or multiple JavaScript files relative to the Django static directory.

    Accepts:
        - Single string: 'assets/js/file.js'
        - List of strings: ['assets/js/file1.js', 'assets/js/file2.js']

    Ensures no duplicates are added.
    """

    # If a single string is passed, convert to list
    if isinstance(static_paths, str):
        static_paths = [static_paths]

    # Ensure it's now a list
    if isinstance(static_paths, (list, tuple)):
        for static_path in static_paths:
            if static_path not in REGISTERED_JS_FILES:
                REGISTERED_JS_FILES.append(static_path)


def get_registered_js():
    """
    Retrieve all registered JavaScript file paths.

    Returns:
        list: A list of strings representing the registered JavaScript files.
    """
    return REGISTERED_JS_FILES


def register_html(
    template_path: str,
    slot: str,
    priority: int = 50,
    page: str = "base",
) -> None:
    """
    Register an HTML template fragment for injection into a layout slot.

    Parameters
    ----------
    template_path : str
        Django template path that renders a valid HTML fragment.
        Example:
            "horilla_theme/slots/tailwind_dynamic_config.html"

    slot : str
        Target layout slot.
        Must be one of:
            - head_start
            - head_end
            - body_start
            - body_end

    priority : int, optional
        Load order priority within the slot.
        Lower values render earlier. Default is 50.

    Behavior
    --------
    - Each (template_path, slot) pair is registered only once
    - Rendering order is deterministic and priority-based
    - No rendering occurs here (template inclusion happens in index.html)
    """
    if slot not in INJECT_ALLOWED_SLOTS:
        raise ValueError(
            f"Invalid slot '{slot}'. Allowed slots: {sorted(INJECT_ALLOWED_SLOTS)}"
        )

    key = (template_path, slot, page)

    if key not in REGISTERED_HTML_PRIORITY:
        REGISTERED_HTML_BLOCKS[slot].append((template_path, page))
        REGISTERED_HTML_PRIORITY[key] = priority


def get_registered_html(slot: str, page: str = "base") -> List[str]:
    """
    Retrieve registered HTML template fragments for a given slot.

    Parameters
    ----------
    slot : str
        Slot name (e.g., "head_start", "body_end")

    Returns
    -------
    list[str]
        List of Django template paths sorted by ascending priority.

    Usage
    -----
        {% load_registered_html "body_end" as body_end_html %}
        {% for tpl in body_end_html %}
            {% include tpl %}
        {% endfor %}
    """
    templates = REGISTERED_HTML_BLOCKS.get(slot, [])

    filtered = [tpl for tpl, tpl_page in templates if tpl_page in (page, "*")]

    return sorted(
        filtered,
        key=lambda tpl: REGISTERED_HTML_PRIORITY.get((tpl, slot, page), 50),
    )
