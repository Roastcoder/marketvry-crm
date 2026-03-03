"""Template tags for loading registered JS/HTML assets."""

from horilla.registry.asset_registry import get_registered_html, get_registered_js

from ._registry import register


@register.simple_tag
def load_registered_js():
    """
    Retrieve all registered JavaScript file paths for inclusion in templates.

    Returns:
        list: List of static file paths for JavaScript files registered by apps.
    """
    return get_registered_js()


@register.simple_tag
def load_registered_html(slot, page="base"):
    """
    Template tag to retrieve all registered HTML template fragments
    for a given slot in the base layout.
    """
    return get_registered_html(slot, page)
