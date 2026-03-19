"""
Views for managing opportunity stages in the CRM system.

This module provides views for creating, updating, deleting, and managing
the order of opportunity stages for different companies.
"""

# Standard library imports
import logging
from functools import cached_property

# Third-party imports (Django)
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.utils.html import format_html
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView, View

from horilla.auth.models import User

# First-party / Horilla imports
from horilla.db import models
from horilla.http import HttpNotFound, HttpResponse, JsonResponse
from horilla.shortcuts import get_object_or_404, redirect, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla_core.models import Company
from horilla_core.progress import ProgressStepsMixin
from horilla_crm.opportunities.filters import OpportunityStageFilter
from horilla_crm.opportunities.forms import OpportunityStageForm
from horilla_crm.opportunities.models import OpportunityStage
from horilla_crm.opportunities.signals import opp_stage_created
from horilla_generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla_utils.middlewares import _thread_local

logger = logging.getLogger(__name__)


class OpportunityStageView(LoginRequiredMixin, HorillaView):
    """
    TemplateView for company information settings page.
    """

    template_name = "opportunity_stage/opportunity_stage_view.html"
    nav_url = reverse_lazy("opportunities:opportunity_stage_nav_view")
    list_url = reverse_lazy("opportunities:opportunity_stage_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required("opportunities.view_opportunitystage"), name="dispatch"
)
class OpportunityStageNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar view for opportunity stages."""

    nav_title = OpportunityStage._meta.verbose_name_plural
    search_url = reverse_lazy("opportunities:opportunity_stage_list_view")
    main_url = reverse_lazy("opportunities:opportunity_stage_view")
    filterset_class = OpportunityStageFilter
    model_name = "OpportunityStage"
    model_app_label = "opportunities"
    nav_width = False
    gap_enabled = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """Return new button configuration if user has create permission."""
        if self.request.user.has_perm("opportunities:create_opportunitystage"):
            return {
                "url": f"""{ reverse_lazy('opportunities:create_opportunity_stage')}?new=true""",
                "attrs": {"id": "opportunity-stage-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.view_opportunitystage"),
    name="dispatch",
)
class OpportunityStageListView(LoginRequiredMixin, HorillaListView):
    """
    opportunity List view
    """

    model = OpportunityStage
    view_id = "opportunity-stage-list"
    filterset_class = OpportunityStageFilter
    search_url = reverse_lazy("opportunities:opportunity_stage_list_view")
    main_url = reverse_lazy("opportunities:opportunity_stage_view")
    save_to_list_option = False
    bulk_select_option = False
    table_width = False
    enable_sorting = False
    table_height_as_class = "h-[calc(_100vh_-_260px_)]"

    def get_queryset(self):
        """Return queryset ordered by stage order."""
        queryset = super().get_queryset()
        queryset = queryset.order_by("order")
        return queryset

    @cached_property
    def col_attrs(self):
        """Return column attributes for draggable order column."""
        return [
            {
                "order": {
                    "is_draggable": "true",
                    "sort_url": reverse_lazy(
                        "opportunities:update_opportunity_stage_order"
                    ),
                }
            }
        ]

    def no_record_add_button(self):
        """Return add button configuration when no records exist."""
        if self.request.user.has_perm("opportunities:create_opportunitystage"):
            return {
                "url": f"""{ reverse_lazy('opportunities:create_opportunity_stage')}?new=true""",
                "attrs": 'id="opportunity-stage-create"',
            }
        return None

    columns = [
        "order",
        "name",
        (_("Is Final Stage"), "is_final_col"),
        "probability",
        "stage_type",
    ]

    actions = [
        {
            "action": _("Edit"),
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "opportunities:change_opportunitystage",
            "attrs": """
                    hx-get="{get_edit_url}?new=true"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    onclick="openModal()"
                    """,
        },
        {
            "action": _("Delete"),
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "opportunities:delete_opportunitystage",
            "attrs": """
                        hx-post="{get_delete_url}"
                        hx-target="#deleteModeBox"
                        hx-swap="innerHTML"
                        hx-trigger="click"
                        hx-vals='{{"check_dependencies": "true"}}'
                        onclick="openDeleteModeModal()"
                    """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.change_opportunitystage"),
    name="dispatch",
)
class ChangeFinalStage(LoginRequiredMixin, View):
    """
    View to change the final stage for a company.
    """

    def post(self, request, *args, **kwargs):
        """Handle POST request to change final stage."""
        stage_id = kwargs.get("pk")

        try:
            new_final_stage = OpportunityStage.objects.get(id=stage_id)

            with transaction.atomic():
                company = new_final_stage.company
                all_stages = list(
                    OpportunityStage.objects.filter(company=company)
                    .select_for_update()
                    .order_by("order")
                )

                temp_order_start = 10000
                for idx, stage in enumerate(all_stages):
                    OpportunityStage.objects.filter(pk=stage.pk).update(
                        order=temp_order_start + idx
                    )

                OpportunityStage.objects.filter(company=company, is_final=True).exclude(
                    pk=new_final_stage.pk
                ).update(is_final=False)

                new_final_stage.is_final = True
                new_final_stage.save()

            messages.success(request, _("Final stage changed successfully."))
            return HttpResponse(
                "<script>htmx.trigger('#reloadButton','click')</script>"
            )

        except OpportunityStage.DoesNotExist:
            messages.error(request, _("Stage not found."))
            return HttpResponse("<script>$('#reloadButton').click();</script>")
        except Exception as e:
            messages.error(request, f"Error changing final stage: {str(e)}")
            return HttpResponse("<script>$('#reloadButton').click();</script>")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.add_opportunitystage"), name="dispatch"
)
class CreateOpportunityStage(LoginRequiredMixin, HorillaSingleFormView):
    """View for creating and editing opportunity stages."""

    model = OpportunityStage
    modal_height = False
    form_class = OpportunityStageForm

    def get_initial(self):
        """Set initial order for new opportunity stages."""
        initial = super().get_initial()
        if not self.kwargs.get("pk"):  # Only set initial order for new stages
            company = (
                getattr(_thread_local, "request", None).active_company
                if hasattr(_thread_local, "request")
                else self.request.user.company
            )
            if company:
                initial["order"] = OpportunityStage.get_next_order_for_company(company)
        return initial

    @cached_property
    def form_url(self):
        """Return form URL based on whether editing or creating."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "opportunities:edit_opportunity_stage", kwargs={"pk": pk}
            )
        return reverse_lazy("opportunities:create_opportunity_stage")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.change_opportunitystage"),
    name="dispatch",
)
class OpportynityToggleOrderFieldView(LoginRequiredMixin, TemplateView):
    """
    HTMX endpoint to toggle the visibility of the order field based on is_final checkbox
    """

    template_name = "opportunity_stage/order_field.html"

    def get_context_data(self, **kwargs):
        """Get context data for order field toggle."""
        context = super().get_context_data(**kwargs)
        is_final = self.request.POST.get("is_final") or self.request.GET.get("is_final")
        current_order_value = self.request.POST.get(
            "order", ""
        ) or self.request.GET.get("order", "")

        context["show_order_field"] = is_final != "on"

        if context["show_order_field"] and not current_order_value:
            company = (
                getattr(_thread_local, "request", None).active_company
                if hasattr(_thread_local, "request")
                else self.request.user.company
            )
            if company:
                current_order_value = OpportunityStage.get_next_order_for_company(
                    company
                )

        context["order_value"] = current_order_value
        return context

    def post(self, request, *args, **kwargs):
        """Handle POST request for order field toggle."""
        return self.get(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.delete_opportunitystage", modal=True),
    name="dispatch",
)
class OpportunityStatusDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View for deleting opportunity stages."""

    model = OpportunityStage

    def get_post_delete_response(self):
        """Return response after successful deletion."""
        return HttpResponse("<script>htmx.trigger('#reloadButton','click');</script>")


@method_decorator(
    permission_required_or_denied("opportunities.add_opportunitystage"), name="dispatch"
)
class UpdateOpportunityStageOrderView(LoginRequiredMixin, View):
    """
    Handles AJAX requests for updating opportunity stage order via drag-and-drop
    """

    def post(self, request, *args, **kwargs):
        """Handle POST request to update opportunity stage order."""
        try:
            ids = request.POST.getlist("ids[]") or request.POST.getlist("ids")
            if not ids:
                return JsonResponse(
                    {"status": "error", "message": "No IDs provided"}, status=400
                )

            with transaction.atomic():
                statuses = {
                    str(s.id): s for s in OpportunityStage.objects.filter(id__in=ids)
                }
                if len(statuses) != len(ids):
                    missing_ids = set(ids) - set(statuses.keys())
                    return JsonResponse(
                        {"status": "error", "message": f"Invalid IDs: {missing_ids}"},
                        status=400,
                    )

                company = statuses[ids[0]].company

                all_stages = OpportunityStage.objects.filter(company=company)
                max_existing_order = (
                    all_stages.aggregate(max_order=models.Max("order"))["max_order"]
                    or 0
                )

                temp_order_start = max_existing_order + 1000

                for i, id in enumerate(ids):
                    status = statuses[id]
                    if not status.is_final:
                        temp_order = temp_order_start + i
                        OpportunityStage.objects.filter(id=status.id).update(
                            order=temp_order
                        )

                for order, id in enumerate(ids, start=1):
                    status = statuses[id]
                    if not status.is_final:
                        OpportunityStage.objects.filter(id=status.id).update(
                            order=order
                        )

                self._ensure_final_stages_last(company=company)

            return JsonResponse({"status": "success"})

        except Exception as e:
            logger.error("Error updating opportunity stage order: %s", e)
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    def _ensure_final_stages_last(self, company):
        """
        Ensures all final stages are ordered after non-final stages
        """
        non_final = list(
            OpportunityStage.objects.filter(company=company, is_final=False).order_by(
                "order", "id"
            )
        )

        final = list(
            OpportunityStage.objects.filter(company=company, is_final=True).order_by(
                "order", "id"
            )
        )

        all_stages = non_final + final

        max_existing_order = (
            OpportunityStage.objects.filter(company=company).aggregate(
                max_order=models.Max("order")
            )["max_order"]
            or 0
        )
        temp_order_start = max_existing_order + 2000

        with transaction.atomic():
            for i, status in enumerate(all_stages):
                temp_order = temp_order_start + i
                OpportunityStage.objects.filter(id=status.id).update(order=temp_order)

            for order, status in enumerate(all_stages, start=1):
                OpportunityStage.objects.filter(id=status.id).update(order=order)


@method_decorator(htmx_required(), name="dispatch")
class LoadOpportunityStagesView(LoginRequiredMixin, View):
    """View to load opportunity stages modal for a company."""

    def get(self, request, company_id):
        """Load and display opportunity stages modal for a company."""
        try:
            company = get_object_or_404(Company, id=company_id)
        except Exception as e:
            raise HttpNotFound(e) from e
        initialization = request.GET.get("initialization") == "true"
        default_stages = [
            {
                "name": _("Prospecting"),
                "order": 1,
                "probability": 10,
                "is_final": False,
            },
            {
                "name": _("Qualification"),
                "order": 2,
                "probability": 20,
                "is_final": False,
            },
            {
                "name": _("Needs Analysis"),
                "order": 3,
                "probability": 30,
                "is_final": False,
            },
            {
                "name": _("Value Proposition"),
                "order": 4,
                "probability": 50,
                "is_final": False,
            },
            {
                "name": _("Id. Decision Makers"),
                "order": 5,
                "probability": 60,
                "is_final": False,
            },
            {
                "name": _("Perception Analysis"),
                "order": 6,
                "probability": 70,
                "is_final": False,
            },
            {
                "name": _("Proposal/Price Quote"),
                "order": 7,
                "probability": 80,
                "is_final": False,
            },
            {
                "name": _("Negotiation/Review"),
                "order": 8,
                "probability": 90,
                "is_final": False,
            },
            {"name": _("Closed Lost"), "order": 9, "probability": 0, "is_final": False},
            {
                "name": _("Closed Won"),
                "order": 10,
                "probability": 100,
                "is_final": True,
            },
        ]

        all_stages = OpportunityStage.all_objects.values(
            "name", "order", "probability", "is_final", "company__name", "company_id"
        ).order_by("company_id", "order")

        raw_company_stages = {}
        for stage in all_stages:
            company_id = stage["company_id"]
            if company_id not in raw_company_stages:
                raw_company_stages[company_id] = {
                    "company_name": stage["company__name"],
                    "stages": [],
                }
            raw_company_stages[company_id]["stages"].append(
                {
                    "name": stage["name"],
                    "order": stage["order"],
                    "probability": stage["probability"],
                    "is_final": stage["is_final"],
                }
            )

        # Create signature for stage comparison
        def create_stage_signature(stages):
            """Create a hashable signature for a set of stages."""
            return tuple(
                (s["name"], s["order"], s["probability"], s["is_final"])
                for s in sorted(stages, key=lambda x: x["order"])
            )

        # Group companies by their stage signatures
        signature_groups = {}
        default_signature = create_stage_signature(default_stages)

        for comp_id, comp_data in raw_company_stages.items():
            signature = create_stage_signature(comp_data["stages"])

            if signature == default_signature:
                continue

            if signature not in signature_groups:
                signature_groups[signature] = []
            signature_groups[signature].append(comp_data)

        company_stages = {}

        group_counter = 1
        for signature, companies in signature_groups.items():
            representative = companies[0]

            if len(companies) > 1:
                _company_names = [comp["company_name"] for comp in companies]
                representative["company_name"] = (
                    f"{representative['company_name']} (+{len(companies)-1} others)"
                )

            company_stages[f"group_{group_counter}"] = representative
            group_counter += 1

        # Build context dictionary
        context = {
            "default_stages": default_stages,
            "company_stages": company_stages,
            "company": company,
            "initialization": initialization,
            "hx_target": (
                "initialize-opportunity-stages" if initialization else "stage-messages"
            ),
            "hx_swap": "outerHTML" if initialization else "innerHTML",
            "hx_push_url": (
                reverse_lazy("horilla_core:home_view") if initialization else "false"
            ),
        }

        # Only add hx_select when initialization is True
        if initialization:
            context["hx_select"] = "#sec1"

        return render(
            request,
            "opportunity_stage/opportunity_stages_modal.html",
            context,
        )


@method_decorator(htmx_required(), name="dispatch")
class CustomOppStagesFormView(LoginRequiredMixin, View):
    """View to display custom opportunity stages form."""

    def get(self, request, company_id):
        """Display custom opportunity stages form for a company."""
        try:
            company = get_object_or_404(Company, id=company_id)
        except Exception as e:
            raise HttpNotFound(e) from e
        initialization = request.GET.get("initialization") == "True"
        all_stages_from_db = OpportunityStage.all_objects.values(
            "name", "order", "probability", "is_final", "company__name", "company_id"
        ).order_by("company_id", "order")

        default_stages = [
            {
                "name": _("Prospecting"),
                "order": 1,
                "probability": 10,
                "is_final": False,
            },
            {
                "name": _("Qualification"),
                "order": 2,
                "probability": 20,
                "is_final": False,
            },
            {
                "name": _("Needs Analysis"),
                "order": 3,
                "probability": 30,
                "is_final": False,
            },
            {
                "name": _("Value Proposition"),
                "order": 4,
                "probability": 50,
                "is_final": False,
            },
            {
                "name": _("Id. Decision Makers"),
                "order": 5,
                "probability": 60,
                "is_final": False,
            },
            {
                "name": _("Perception Analysis"),
                "order": 6,
                "probability": 70,
                "is_final": False,
            },
            {
                "name": _("Proposal/Price Quote"),
                "order": 7,
                "probability": 80,
                "is_final": False,
            },
            {
                "name": _("Negotiation/Review"),
                "order": 8,
                "probability": 90,
                "is_final": False,
            },
            {"name": _("Closed Lost"), "order": 9, "probability": 0, "is_final": False},
            {
                "name": _("Closed Won"),
                "order": 10,
                "probability": 100,
                "is_final": True,
            },
        ]

        unique_stages = {}

        for stage in default_stages:
            unique_stages[stage["name"]] = stage

        for stage in all_stages_from_db:
            stage_name = stage["name"]
            if stage_name not in unique_stages:
                unique_stages[stage_name] = {
                    "name": stage["name"],
                    "order": stage["order"],
                    "probability": stage["probability"],
                    "is_final": stage["is_final"],
                }

        combined_stages = []
        for i, (_name, stage) in enumerate(unique_stages.items(), 1):
            stage_copy = stage.copy()
            stage_copy["order"] = i
            combined_stages.append(stage_copy)

        # Build context dictionary
        context = {
            "company": company,
            "company_stages": {company_id: combined_stages},
            "default_stages": combined_stages,
            "initialization": initialization,
            "hx_target": (
                "initialize-opportunity-stages" if initialization else "stage-messages"
            ),
            "hx_swap": "outerHTML" if initialization else "innerHTML",
            "hx_push_url": (
                reverse_lazy("horilla_core:home_view") if initialization else "false"
            ),
        }

        # Only add hx_select when initialization is True
        if initialization:
            context["hx_select"] = "#sec1"

        return render(
            request,
            "opportunity_stage/custom_stages_form_opp.html",
            context,
        )


@method_decorator(csrf_exempt, name="dispatch")
@method_decorator(htmx_required(), name="dispatch")
class SaveCustomOppStagesView(LoginRequiredMixin, View):
    """View to save custom opportunity stages for a company."""

    def get_signal_kwargs(self, company, request, initialization, stages=None):
        """
        Extension point: Override this method to pass additional data to signal.
        Clients can add custom data without modifying source code.
        """
        return {
            "company": company,
            "request": request,
            "view": self,
            "initialization": initialization,
            "stages": stages or [],
        }

    def _error_response(self, request, message):
        """Return HTMX response that shows error in form (single-form-view style, oob into #custom-stages-error)."""
        return render(
            request,
            "opportunity_stage/save_custom_opp_stages_response.html",
            {"error_message": message},
            status=200,
        )

    def _success_response(self, request):
        """Return HTMX response that clears any previous error in the form."""
        return render(
            request,
            "opportunity_stage/save_custom_opp_stages_response.html",
            {"error_message": None},
            status=200,
        )

    def post(self, request, company_id):
        """Handle POST request to save custom opportunity stages."""
        try:
            company = get_object_or_404(Company, id=company_id)
        except Exception as e:
            raise HttpNotFound(e) from e
        stage_names = request.POST.getlist("stage_name_custom[]")
        stage_orders = request.POST.getlist("stage_order_custom[]")
        stage_probabilities = request.POST.getlist("stage_probability_custom[]")
        stage_is_finals = request.POST.getlist("stage_is_final_custom[]")
        initialization = request.GET.get("initialization") == "True"

        # Validate that all lists have the same length
        n = len(stage_names)
        if len(stage_orders) != n or len(stage_probabilities) != n:
            return self._error_response(
                request,
                "Invalid form data: order or probability missing for one or more stages.",
            )

        OpportunityStage.all_objects.filter(company=company).delete()

        try:
            for i, stage_name in enumerate(stage_names):
                is_final = str(i) in stage_is_finals
                name = stage_name.strip()
                if not name:
                    return self._error_response(
                        request, f"Stage name cannot be empty for stage {i+1}."
                    )
                try:
                    order = int(stage_orders[i])
                except (ValueError, TypeError):
                    return self._error_response(
                        request,
                        f'Invalid order for stage {i+1} ("{name}"). Use a whole number.',
                    )
                try:
                    probability = float(stage_probabilities[i])
                except (ValueError, TypeError):
                    return self._error_response(
                        request,
                        f'Invalid probability for stage "{name}". Use a number between 0 and 100.',
                    )
                if probability < 0 or probability > 100:
                    return self._error_response(
                        request,
                        f"Probability must be between 0 and 100 for stage: {name}",
                    )
                if OpportunityStage.all_objects.filter(
                    company=company, name=name
                ).exists():
                    return self._error_response(
                        request, f'Stage "{name}" already exists for this company.'
                    )
                if probability == 100.0:
                    stage_type = "won"
                elif probability == 0.0:
                    stage_type = "lost"
                else:
                    stage_type = "open"

                OpportunityStage.all_objects.create(
                    company=company,
                    name=name,
                    order=order,
                    probability=probability,
                    is_final=is_final,
                    stage_type=stage_type,
                )
            messages.success(
                request,
                f"Successfully created {company} and associated Opportunity Stages.",
            )
            stages = list(
                OpportunityStage.all_objects.filter(company=company).order_by("order")
            )
            signal_kwargs = self.get_signal_kwargs(
                company=company,
                request=request,
                initialization=initialization,
                stages=stages,
            )

            responses = opp_stage_created.send(sender=self.__class__, **signal_kwargs)

            for receiver, response in responses:
                if isinstance(response, HttpResponse):
                    return response

            if initialization:
                request.session.pop("db_password", None)
                request.session.pop("company_id", None)
                response = HttpResponse()
                response["HX-Redirect"] = "/"
                return response

            branches_view_url = reverse_lazy("horilla_core:branches_view")
            response_html = format_html(
                "<span "
                'hx-trigger="load" '
                'hx-get="{}" '
                'hx-select="#branches-view" '
                'hx-target="#branches-view" '
                'hx-swap="outerHTML" '
                'hx-on::after-request="closeContentModal()"'
                'hx-select-oob="#dropdown-companies">'
                "</span>"
                '<div id="custom-stages-error" class="mb-4" hx-swap-oob="true"></div>',
                branches_view_url,
            )
            return HttpResponse(response_html)

        except Exception:
            return self._error_response(
                request,
                "An error occurred while saving stages. Please try again.",
            )


@method_decorator(htmx_required(), name="dispatch")
@method_decorator(csrf_exempt, name="dispatch")
class CreateOppStageGroupView(LoginRequiredMixin, View):
    """View to create opportunity stage group for a company."""

    def get_signal_kwargs(self, company, request, initialization):
        """
        Extension point: Override this method to pass additional data to signal.
        Clients can add custom data without modifying source code.
        """
        return {
            "company": company,
            "request": request,
            "view": self,
            "initialization": initialization,
        }

    def post(self, request, pk):
        """Handle POST request to create opportunity stage group."""
        try:
            company = get_object_or_404(Company, pk=pk)
        except Exception as e:
            raise HttpNotFound(e) from e
        stage_names = request.POST.getlist("stage_name")
        stage_orders = request.POST.getlist("stage_order")
        stage_probabilities = request.POST.getlist("stage_probability")
        stage_is_finals = request.POST.getlist("stage_is_final")
        initialization = request.GET.get("initialization") == "True"

        try:
            created_stages = []
            for i, _stage_name in enumerate(stage_names):
                is_final_value = (
                    stage_is_finals[i] if i < len(stage_is_finals) else "false"
                )
                is_final = is_final_value.lower() in ["true", "on", "1", "yes"]

                try:
                    order = int(stage_orders[i])
                    probability = float(stage_probabilities[i])
                except (ValueError, IndexError) as e:
                    response = render(
                        request,
                        "common/message_fragment.html",
                        {"message": f"Invalid numeric value for stage {i+1}: {str(e)}"},
                    )
                    response.status_code = 400
                    return response

                if probability < 0 or probability > 100:
                    response = render(
                        request,
                        "common/message_fragment.html",
                        {
                            "message": f"Probability must be between 0 and 100 for stage: {stage_names[i]}"
                        },
                    )
                    response.status_code = 400
                    return response

                if OpportunityStage.objects.filter(
                    name=stage_names[i], company=company
                ).exists():
                    response = render(
                        request,
                        "common/message_fragment.html",
                        {
                            "message": f'Stage "{stage_names[i]}" already exists for this company.',
                        },
                    )
                    response.status_code = 400
                    return response

                if probability == 100.0:
                    stage_type = "won"
                elif probability == 0.0:
                    stage_type = "lost"
                else:
                    stage_type = "open"

                stage = OpportunityStage.objects.create(
                    name=stage_names[i],
                    order=order,
                    probability=probability,
                    is_final=is_final,
                    company=company,
                    created_by=(
                        request.user
                        if request.user.is_authenticated
                        else User.objects.first()
                    ),
                    stage_type=stage_type,
                )
                created_stages.append(stage)
            messages.success(
                request,
                f"Successfully created {company} and associated Opportunity Stages.",
            )
            signal_kwargs = self.get_signal_kwargs(
                company=company, request=request, initialization=initialization
            )

            responses = opp_stage_created.send(sender=self.__class__, **signal_kwargs)

            for receiver, response in responses:
                if isinstance(response, HttpResponse):
                    return response

            if initialization:
                request.session.pop("db_password", None)
                request.session.pop("company_id", None)
                response = HttpResponse()
                response["HX-Redirect"] = "/"
                return response

            branches_view_url = reverse_lazy("horilla_core:branches_view")
            response_html = format_html(
                "<span "
                'hx-trigger="load" '
                'hx-get="{}" '
                'hx-select="#branches-view" '
                'hx-target="#branches-view" '
                'hx-swap="outerHTML" '
                'hx-on::after-request="closeContentModal()"'
                'hx-select-oob="#dropdown-companies">'
                "</span>",
                branches_view_url,
            )
            return HttpResponse(response_html)

        except Exception as e:
            print(f"Error:{e}")
            response = render(
                request,
                "common/message_fragment.html",
                {"message": f"Error creating stages: {str(e)}"},
            )
            response.status_code = 500
            return response


class InitializeDatabaseOpportunityStages(View, ProgressStepsMixin):
    """View for initializing opportunity stages during database setup."""

    current_step = 6

    def get(self, request, *args, **kwargs):
        """Display opportunity stages initialization page."""
        company_id = request.POST.get("company_id") or request.session.get("company_id")
        if request.session.get("db_password") == settings.DB_INIT_PASSWORD:
            context = {
                "progress_steps": self.get_progress_steps(),
                "current_step": self.current_step,
                "company_id": company_id,
            }
            return render(
                request, "opportunity_stage/oppor_stages_initialize.html", context
            )
        return redirect("/")
