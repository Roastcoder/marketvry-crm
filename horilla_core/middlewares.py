"""Custom middleware classes for Horilla core functionalities.

This module provides middleware for:
- Setting the active company for the logged-in user.
- Managing user-specific time zones.
- Handling custom Horilla exceptions.
"""

# Standard library imports
import logging

# Django imports
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin

from horilla.http import HttpNotFound, HttpResponse, HttpResponseNotAllowed
from horilla.menu.sub_section_menu import sub_section_menu as menu_registry
from horilla.shortcuts import redirect, render

# First-party imports (Horilla)
from horilla.urls import Resolver404, resolve

from .models import Company

logger = logging.getLogger(__name__)


class ActiveCompanyMiddleware:
    """Middleware to attach the active company to the request object."""

    def __init__(self, get_response):
        """Initialize middleware with the given get_response function."""
        self.get_response = get_response

    def __call__(self, request):
        """Set the active company for the authenticated user."""
        request.active_company = None
        if request.user.is_authenticated:
            company_id = request.session.get("active_company_id")
            if company_id:
                try:
                    request.active_company = Company.objects.get(id=company_id)
                except Company.DoesNotExist:  # Fixed pylint complaint
                    request.active_company = getattr(request.user, "company", None)
            else:
                request.active_company = getattr(request.user, "company", None)
        return self.get_response(request)


class TimezoneMiddleware:
    """Middleware to activate timezone based on user preferences."""

    def __init__(self, get_response):
        """Initialize middleware with the given get_response function."""
        self.get_response = get_response

    def __call__(self, request):
        """Activate or deactivate timezone depending on authentication."""
        if request.user.is_authenticated:
            tzname = getattr(request.user, "time_zone", "UTC") or "UTC"
            timezone.activate(tzname)
        else:
            timezone.deactivate()

        return self.get_response(request)


class HorillaExceptionMiddleware:
    """Middleware to catch and handle Horilla-specific exceptions."""

    def __init__(self, get_response):
        """Initialize middleware with the given get_response function."""
        self.get_response = get_response

    def __call__(self, request):
        """Process requests and catch HttpNotFound exceptions."""
        try:
            return self.get_response(request)
        except HttpNotFound as exc:
            return exc.as_response(request)

    def process_exception(self, request, exception):
        """Handle HttpNotFound exceptions raised outside __call__."""
        if isinstance(exception, HttpNotFound):
            return exception.as_response(request)
        return None


class Horilla405Middleware:
    """Middleware to show a custom 405 page when DEBUG is False."""

    def __init__(self, get_response):
        """Store the next middleware or view in the chain."""
        self.get_response = get_response

    def __call__(self, request):
        """Return the response or render 405.html if method not allowed."""
        response = self.get_response(request)

        if isinstance(response, HttpResponseNotAllowed):
            """Render a custom 405 error page."""
            return render(request, "405.html", status=405)

        return response


class SVGSecurityMiddleware:
    """Middleware to add security headers for SVG files."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.endswith(".svg") and response.status_code == 200:
            response["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'unsafe-inline';"
            )
            response["X-Content-Type-Options"] = "nosniff"
        return response


class HTMXRedirectMiddleware:
    """
    Middleware to handle HTMX redirects for unauthenticated requests.
    Add to MIDDLEWARE in settings.py
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Check if this is a redirect response to login page from an HTMX request
        if (
            response.status_code == 302
            and (
                request.headers.get("HX-Request") or request.META.get("HTTP_HX_REQUEST")
            )
            and "login" in response.url
        ):

            # Get the current page URL from HX-Current-URL header or Referer
            current_url = (
                request.headers.get("HX-Current-URL")
                or request.headers.get("Referer")
                or request.path
            )

            # Parse the login URL and replace the 'next' parameter
            from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

            # Extract just the path from current_url (remove domain)
            current_path = urlparse(current_url).path

            parsed = urlparse(response.url)
            query_params = parse_qs(parsed.query)

            # Replace 'next' with just the path (not full URL)
            query_params["next"] = [current_path]
            new_query = urlencode(query_params, doseq=True)

            # Reconstruct the URL with updated 'next' parameter
            new_login_url = urlunparse(
                (
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    new_query,
                    parsed.fragment,
                )
            )

            # Convert to HX-Redirect
            new_response = HttpResponse(status=200)
            new_response["HX-Redirect"] = new_login_url
            return new_response

        return response


class EnsureSectionMiddleware(MiddlewareMixin):
    """Middleware to ensure 'section' parameter is present and valid in URLs."""

    def process_request(self, request):
        """Check and enforce 'section' parameter in GET requests."""
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None

        # Skip for static files, admin, etc.
        if request.path.startswith("/static/") or request.path.startswith("/admin/"):
            return None

        # Skip all POST requests (API endpoints, form submissions, etc.)
        if request.method == "POST":
            return None

        # Check if this is an HTMX request
        is_htmx = request.headers.get("HX-Request") == "true"

        # Check if this is an AJAX/API request
        is_ajax = (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or request.content_type == "application/json"
            or "application/json" in request.headers.get("Accept", "")
        )

        # If it's HTMX request or AJAX request, skip all section validation/modification
        # (whether hx-push-url is true or false, we don't modify sections for HTMX/AJAX)
        if is_htmx or is_ajax:
            return None

        # Get current section value
        current_section = request.GET.get("section", "").strip()

        # If a section is already present in the request, do not modify it.
        # Only when the section parameter is missing or empty, derive it from the path.
        if not current_section:
            section = self.get_section_from_path(request.path)

            # Only redirect if a valid section was found
            if section:
                query_params = request.GET.copy()
                query_params["section"] = section

                new_url = f"{request.path}?{query_params.urlencode()}"
                return redirect(new_url)

        return None

    def get_valid_sections(self):
        """Get all valid section values from menu_registry"""
        valid_sections = set()
        try:
            for menu_cls in menu_registry:
                section = getattr(menu_cls, "section", None)
                if section:
                    valid_sections.add(section)
        except Exception as e:
            logger.warning("Error getting valid sections: %s", e)

        return valid_sections

    def get_section_from_path(self, path):
        """Extract section by matching path with menu_registry URLs"""
        try:
            # Special case: root path mapped to home view
            # If the resolved URL name is 'home_view', we want section to be 'home'
            try:
                resolved_root = resolve(path)
                if getattr(resolved_root, "url_name", None) == "home_view":
                    return "home"
            except Resolver404:
                # If root cannot be resolved, fall back to normal logic
                pass

            # First, try to match by URL
            for menu_cls in menu_registry:
                menu_url = str(getattr(menu_cls, "url", ""))

                # Check if the current path matches the menu URL
                if menu_url and path.startswith(menu_url):
                    section = getattr(menu_cls, "section", None)
                    if section:
                        return section

            # If no match found by URL, try to resolve and match by app_label
            try:
                resolved = resolve(path)
                if hasattr(resolved, "app_name") and resolved.app_name:
                    for menu_cls in menu_registry:
                        if hasattr(menu_cls, "app_label"):
                            cls_app_label = getattr(menu_cls, "app_label", None)
                            if cls_app_label == resolved.app_name:
                                section = getattr(menu_cls, "section", None)
                                if section:
                                    return section
            except Resolver404:
                pass

        except Exception as e:
            logger.warning("Error in get_section_from_path: %s", e)

        return None
