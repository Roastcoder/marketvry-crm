"""Template filters for URL manipulation."""

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from ._registry import register


@register.filter
def remove_query_param(url, param):
    """
    Removes a query parameter from a URL string.
    Example: {{ request.get_full_path|remove_query_param:"section" }}
    """
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query, keep_blank_values=True)
    query_params.pop(param, None)
    new_query = urlencode(query_params, doseq=True)
    cleaned_url = urlunparse(parsed_url._replace(query=new_query))
    return cleaned_url
