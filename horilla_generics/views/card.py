"""
Card (tile) view for displaying list data in a grid of cards.
Uses the same data and context as HorillaListView with a card layout.
"""

# Standard library
import logging

from django.http import HttpResponse

# Django
from django.template.loader import render_to_string

# First-party (Horilla)
from horilla.shortcuts import render
from horilla_generics.views.list import HorillaListView

logger = logging.getLogger(__name__)


class HorillaCardView(HorillaListView):
    """
    View for displaying data in a card (tile) grid layout.
    Reuses HorillaListView queryset, filters, and context with a card template.
    """

    template_name = "card_view.html"
    bulk_select_option = False
    table_class = False
    table_width = False
    paginate_by = 24

    def render_to_response(self, context, **response_kwargs):
        """Override to use card template for HTMX and normal requests."""
        is_htmx = self.request.headers.get("HX-Request") == "true"
        context["request_params"] = self.request.GET.copy()

        if is_htmx:
            page_kwarg = getattr(self, "page_kwarg", "page")
            if self.request.GET.get(page_kwarg):
                html = render_to_string(
                    "partials/card_view_load_more.html",
                    context,
                    request=self.request,
                )
                return HttpResponse(html)
            return render(self.request, "card_view.html", context)

        return super(HorillaListView, self).render_to_response(
            context, **response_kwargs
        )
