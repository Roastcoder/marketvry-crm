"""
Safe redirect URL validation for Horilla.

Prevents open redirects (CWE-601) using Django's url_has_allowed_host_and_scheme.
"""

from django.utils.http import url_has_allowed_host_and_scheme


def safe_url(request, next_url, fallback="/"):
    """
    Return next_url if it is safe for redirects, otherwise fallback.
    Prevents open redirects (CWE-601) using url_has_allowed_host_and_scheme.
    """
    if not next_url:
        return fallback
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return fallback
    return next_url
