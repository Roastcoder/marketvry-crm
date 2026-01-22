"""Views for opportunities module."""

# Standard library imports
from urllib.parse import urlencode

# Third-party imports (Django)
from django.apps import apps
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property  # type: ignore
from django.utils.translation import gettext_lazy as _

# First-party / Horilla imports
from horilla_activity.views import HorillaActivitySectionView
from horilla_core.decorators import (
    htmx_required,
    permission_required,
    permission_required_or_denied,
)
from horilla_core.utils import is_owner
from horilla_crm.contacts.models import ContactAccountRelationship
from horilla_crm.opportunities.filters import OpportunityFilter
from horilla_crm.opportunities.forms import OpportunityFormClass, OpportunitySingleForm
from horilla_crm.opportunities.models import (
    Opportunity,
    OpportunityContactRole,
    OpportunitySettings,
)
from horilla_crm.opportunities.signals import set_opportunity_contact_id
from horilla_generics.mixins import RecentlyViewedMixin
from horilla_generics.views import (
    HorillaDetailSectionView,
    HorillaDetailTabView,
    HorillaDetailView,
    HorillaHistorySectionView,
    HorillaKanbanView,
    HorillaListView,
    HorillaMultiStepFormView,
    HorillaNavView,
    HorillaNotesAttachementSectionView,
    HorillaRelatedListSectionView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla_utils.middlewares import _thread_local


class OpportunityView(LoginRequiredMixin, HorillaView):
    """Render the opportunities page."""

    nav_url = reverse_lazy("opportunities:opportunities_nav")
    list_url = reverse_lazy("opportunities:opportunities_list")
    kanban_url = reverse_lazy("opportunities:opportunities_kanban")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityNavbar(LoginRequiredMixin, HorillaNavView):
    """Navigation bar view for opportunities."""

    nav_title = Opportunity._meta.verbose_name_plural
    search_url = reverse_lazy("opportunities:opportunities_list")
    main_url = reverse_lazy("opportunities:opportunities_view")
    filterset_class = OpportunityFilter
    kanban_url = reverse_lazy("opportunities:opportunities_kanban")
    model_name = "Opportunity"
    model_app_label = "opportunities"
    exclude_kanban_fields = "owner"
    enable_actions = True

    @cached_property
    def new_button(self):
        """Return new button configuration for opportunities."""
        if self.request.user.has_perm(
            "opportunities.add_opportunity"
        ) or self.request.user.has_perm("opportunities.add_own_opportunity"):
            return {
                "url": f"""{reverse_lazy("opportunities:opportunity_create")}?new=true""",
                "attrs": {"id": "opportunity-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityListView(LoginRequiredMixin, HorillaListView):
    """
    Opportunity List view
    """

    model = Opportunity
    view_id = "opportunity-container"
    filterset_class = OpportunityFilter
    search_url = reverse_lazy("opportunities:opportunities_list")
    main_url = reverse_lazy("opportunities:opportunities_view")
    bulk_update_fields = ["owner", "opportunity_type", "lead_source"]
    header_attrs = [
        {"email": {"style": "width: 300px;"}, "title": {"style": "width: 200px;"}},
    ]

    @cached_property
    def col_attrs(self):
        """Return column attributes for opportunity list view."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        attrs = {
            "hx-get": f"{{get_detail_url}}?{query_string}",
            "hx-target": "#mainContent",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
            "hx-select": "#mainContent",
            "permission": "opportunities.view_opportunity",
            "own_permission": "opportunities.view_own_opportunity",
            "owner_field": "owner",
        }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]

    def no_record_add_button(self):
        """Return add button configuration when no records exist."""
        if self.request.user.has_perm(
            "opportunities.add_opportunity"
        ) or self.request.user.has_perm("opportunities.add_own_opportunity"):
            return {
                "url": f"""{ reverse_lazy('opportunities:opportunity_create')}?new=true""",
                "attrs": 'id="opportunity-create"',
            }
        return None

    columns = [
        "name",
        "amount",
        "close_date",
        "stage",
        "opportunity_type",
        "primary_campaign_source",
    ]

    opp_permissions = {
        "permission": "opportunities.change_opportunity",
        "own_permission": "opportunities.change_own_opportunity",
        "owner_field": "owner",
    }

    actions = [
        {
            **opp_permissions,
            "action": _("Edit"),
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "attrs": """
                    hx-get="{get_edit_url}?new=true"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    onclick="openModal()"
                    """,
        },
        {
            **opp_permissions,
            "action": _("Change Owner"),
            "src": "assets/icons/a2.svg",
            "img_class": "w-4 h-4",
            "attrs": """
                    hx-get="{get_change_owner_url}?new=true"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    onclick="openModal()"
                    """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "opportunities.delete_opportunity",
            "own_permission": "opportunities.delete_own_opportunity",
            "owner_field": "owner",
            "attrs": """
                        hx-post="{get_delete_url}"
                        hx-target="#deleteModeBox"
                        hx-swap="innerHTML"
                        hx-trigger="click"
                        hx-vals='{{"check_dependencies": "true"}}'
                        onclick="openDeleteModeModal()"
                    """,
        },
        {
            "action": _("Duplicate"),
            "src": "assets/icons/duplicate.svg",
            "img_class": "w-4 h-4",
            "permission": "opportunities.add_opportunity",
            "own_permission": "opportunities.add_own_opportunity",
            "owner_field": "owner",
            "attrs": """
                            hx-get="{get_duplicate_url}?duplicate=true"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.delete_opportunity", modal=True),
    name="dispatch",
)
class OpportunityDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View for deleting opportunities."""

    model = Opportunity

    def get_post_delete_response(self):
        """Return response after deleting opportunity."""
        return HttpResponse("<script>htmx.trigger('#reloadButton','click');</script>")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityKanbanView(LoginRequiredMixin, HorillaKanbanView):
    """
    Lead Kanban view
    """

    model = Opportunity
    view_id = "opportunity-kanban"
    filterset_class = OpportunityFilter
    search_url = reverse_lazy("opportunities:opportunities_list")
    main_url = reverse_lazy("opportunities:opportunities_view")
    group_by_field = "stage"

    actions = OpportunityListView.actions

    @cached_property
    def kanban_attrs(self):
        """
        Returns attributes for kanban cards (as a dict).
        """
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")

        query_string = urlencode(query_params)
        return {
            "hx-get": f"{{get_detail_url}}?{query_string}",
            "hx-target": "#mainContent",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
            "hx-select": "#mainContent",
            "permission": "opportunities.view_opportunity",
            "own_permission": "opportunities.view_own_opportunity",
            "owner_field": "owner",
        }

    columns = [
        "name",
        "amount",
        "owner",
        "close_date",
        "expected_revenue",
    ]


@method_decorator(htmx_required, name="dispatch")
class OpportunityMultiStepFormView(LoginRequiredMixin, HorillaMultiStepFormView):
    """Multi-step form view for creating and editing opportunities."""

    form_class = OpportunityFormClass
    model = Opportunity
    total_steps = 3
    fullwidth_fields = ["description"]
    dynamic_create_fields = ["stage"]
    detail_url_name = "opportunities:opportunity_detail_view"
    dynamic_create_field_mapping = {
        "stage": {"full_width_fields": ["description"]},
    }

    single_step_url_name = {
        "create": "opportunities:opportunity_single_create",
        "edit": "opportunities:opportunity_single_edit",
    }

    @cached_property
    def form_url(self):
        """Return form URL for create or update view."""
        pk = self.kwargs.get("pk")
        if pk:
            return reverse_lazy("opportunities:opportunity_edit", kwargs={"pk": pk})
        return reverse_lazy("opportunities:opportunity_create")

    step_titles = {
        "1": _("Opportunity Information"),
        "2": _("Additional Information"),
        "3": _("Description"),
    }

    def get_initial(self):
        """Get initial form data with account ID if provided."""
        initial = super().get_initial()
        account_id = self.request.GET.get("id")
        initial["account"] = account_id
        return initial


@method_decorator(htmx_required, name="dispatch")
class OpportunitySingleFormView(LoginRequiredMixin, HorillaSingleFormView):
    """opportunity Create/Update Single Page View"""

    model = Opportunity
    form_class = OpportunitySingleForm
    full_width_fields = ["description"]
    dynamic_create_fields = ["stage"]
    detail_url_name = "opportunities:opportunity_detail_view"
    dynamic_create_field_mapping = {
        "stage": {"full_width_fields": ["description"]},
    }

    multi_step_url_name = {
        "create": "opportunities:opportunity_create",
        "edit": "opportunities:opportunity_edit",
    }

    @cached_property
    def form_url(self):
        """Form URL for lead"""
        pk = self.kwargs.get("pk")
        if pk:
            return reverse_lazy(
                "opportunities:opportunity_single_edit", kwargs={"pk": pk}
            )
        return reverse_lazy("opportunities:opportunity_single_create")

    def get_initial(self):
        """Get initial form data with account ID from query parameters."""
        initial = super().get_initial()
        account_id = self.request.GET.get("id")
        initial["account"] = account_id
        return initial


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("opportunities.add_opportunity"), name="dispatch"
)
class RelatedOpportunityFormView(LoginRequiredMixin, HorillaMultiStepFormView):
    """Multi-step form view for creating opportunities related to contacts."""

    form_class = OpportunityFormClass
    model = Opportunity
    total_steps = 3
    fullwidth_fields = ["description"]
    dynamic_create_fields = ["stage"]
    save_and_new = False
    dynamic_create_field_mapping = {
        "stage": {"full_width_fields": ["description"]},
    }

    @cached_property
    def form_url(self):
        """Return form URL for create or update view."""
        pk = self.kwargs.get("pk")
        if pk:
            return reverse_lazy("opportunities:opportunity_edit", kwargs={"pk": pk})
        return reverse_lazy("opportunities:opportunity_create")

    step_titles = {
        "1": _("Opportunity Information"),
        "2": _("Additional Information"),
        "3": _("Description"),
    }

    def get_initial(self):
        """Get initial form data with contact ID if provided."""
        initial = super().get_initial()
        contact_id = self.request.GET.get("id")

        if contact_id:
            Contact = apps.get_model("contacts", "Contact")
            contact = Contact.objects.filter(pk=contact_id).first()
            if contact:
                rel = contact.account_relationships.first()
                account_id = rel.account.pk if rel else None
        initial["account"] = account_id
        return initial

    def form_valid(self, form):
        step = self.get_initial_step()

        if step == self.total_steps:
            contact_id = self.request.GET.get("id")
            if contact_id:
                set_opportunity_contact_id(
                    contact_id=contact_id, company=self.request.active_company
                )
            super().form_valid(form)
            return HttpResponse(
                "<script>htmx.trigger('#tab-opportunities-btn','click');closeModal();</script>"
            )

        return super().form_valid(form)

    def get(self, request, *args, **kwargs):
        opportunity_id = self.kwargs.get("pk")
        if request.user.has_perm(
            "opportunities.change_opportunity"
        ) or request.user.has_perm("opportunities.add_opportunity"):
            return super().get(request, *args, **kwargs)

        if opportunity_id:
            opportunity = get_object_or_404(Opportunity, pk=opportunity_id)
            if opportunity.owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "error/403.html")


@method_decorator(htmx_required, name="dispatch")
class OpportunityChangeOwnerForm(LoginRequiredMixin, HorillaSingleFormView):
    """Form view for changing opportunity owner."""

    model = Opportunity
    fields = ["owner"]
    full_width_fields = ["owner"]
    modal_height = False
    form_title = _("Change Owner")

    @cached_property
    def form_url(self):
        """Return form URL for change owner view."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "opportunities:opportunity_change_owner", kwargs={"pk": pk}
            )
        return None

    def get(self, request, *args, **kwargs):
        opportunity_id = self.kwargs.get("pk")
        if request.user.has_perm(
            "opportunities.change_opportunity"
        ) or request.user.has_perm("opportunities.add_opportunity"):
            return super().get(request, *args, **kwargs)

        if opportunity_id:
            opportunity = get_object_or_404(Opportunity, pk=opportunity_id)
            if opportunity.owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "error/403.html")


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityDetailView(RecentlyViewedMixin, LoginRequiredMixin, HorillaDetailView):
    """Detail view for opportunities."""

    model = Opportunity
    pipeline_field = "stage"
    tab_url = reverse_lazy("opportunities:opportunity_detail_view_tabs")
    actions = OpportunityListView.actions
    breadcrumbs = [
        ("Sales", "leads:leads_view"),
        ("Opportunites", "opportunities:opportunities_view"),
    ]

    body = [
        "name",
        "amount",
        "expected_revenue",
        "quantity",
        "close_date",
        "probability",
        "forecast_category",
    ]


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityDetailViewTabView(LoginRequiredMixin, HorillaDetailTabView):
    """Detail view tab view for opportunities."""

    def __init__(self, **kwargs):
        request = getattr(_thread_local, "request", None)
        self.request = request
        self.object_id = self.request.GET.get("object_id")
        super().__init__(**kwargs)

    urls = {
        "details": "opportunities:opportunity_details_tab",
        "activity": "opportunities:opportunity_activity_detail_view",
        "related_lists": "opportunities:opportunity_related_lists",
        "notes_attachments": "opportunities:opportunity_notes_attachments",
        "history": "opportunities:opportunity_history_tab_view",
    }


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityDetailTab(LoginRequiredMixin, HorillaDetailSectionView):
    """Detail tab view for opportunities."""

    model = Opportunity
    non_editable_fields = ["expected_revenue"]
    excluded_fields = [
        "id",
        "created_at",
        "additional_info",
        "updated_at",
        "history",
        "is_active",
        "created_by",
        "updated_by",
        "company",
        "forecast_category",
    ]


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityActivityTabView(LoginRequiredMixin, HorillaActivitySectionView):
    """
    Activity Tab View
    """

    model = Opportunity


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunitiesNotesAndAttachments(
    LoginRequiredMixin, HorillaNotesAttachementSectionView
):
    """Notes and attachments section view for opportunities."""

    model = Opportunity


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityHistoryTabView(LoginRequiredMixin, HorillaHistorySectionView):
    """
    History Tab View
    """

    model = Opportunity


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityRelatedLists(LoginRequiredMixin, HorillaRelatedListSectionView):
    """Related lists section view for opportunities."""

    model = Opportunity

    @cached_property
    def related_list_config(self):
        """Return related list configuration for opportunities."""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        pk = self.request.GET.get("object_id")
        referrer_url = "opportunity_detail_view"
        contact_col_attrs = [
            {
                "first_name": {
                    "permission": "contacts.view_contact",
                    "own_permission": "contacts.view_own_contact",
                    "owner_field": "contact_owner",
                    "hx-get": f"{{get_detail_url}}?referrer_app={self.model._meta.app_label}&referrer_model={self.model._meta.model_name}&referrer_id={pk}&referrer_url={referrer_url}&{query_string}",
                    "hx-target": "#mainContent",
                    "hx-swap": "outerHTML",
                    "hx-push-url": "true",
                    "hx-select": "#mainContent",
                }
            }
        ]
        config = {
            "custom_related_lists": {
                "contact": {
                    "app_label": "contacts",
                    "model_name": "Contact",
                    "intermediate_model": "OpportunityContactRole",
                    "intermediate_field": "contact",
                    "related_field": "opportunity",
                    "config": {
                        "title": _("Contact Roles"),
                        "columns": [
                            (
                                self.model._meta.get_field("contact_roles")
                                .related_model._meta.get_field("contact")
                                .related_model._meta.get_field("first_name")
                                .verbose_name,
                                "first_name",
                            ),
                            (
                                self.model._meta.get_field("contact_roles")
                                .related_model._meta.get_field("contact")
                                .related_model._meta.get_field("last_name")
                                .verbose_name,
                                "last_name",
                            ),
                            (
                                self.model._meta.get_field("contact_roles")
                                .related_model._meta.get_field("role")
                                .verbose_name,
                                "opportunity_roles__role",
                            ),
                            (
                                self.model._meta.get_field("contact_roles")
                                .related_model._meta.get_field("is_primary")
                                .verbose_name,
                                "opportunity_roles__is_primary",
                            ),
                        ],
                        "can_add": self.request.user.has_perm(
                            "opportunities.add_opportunitycontactrole"
                        )
                        and (
                            (
                                is_owner(Opportunity, pk)
                                and self.request.user.has_perm(
                                    "opportunities.change_own_opportunity"
                                )
                            )
                            or self.request.user.has_perm(
                                "opportunities.change_opportunity"
                            )
                        ),
                        "add_url": reverse_lazy(
                            "opportunities:add_opportunity_contact_role"
                        ),
                        "actions": [
                            {
                                "action": "edit",
                                "src": "/assets/icons/edit.svg",
                                "img_class": "w-4 h-4",
                                "permission": "opportunities.change_opportunitycontactrole",
                                "own_permission": "opportunities.change_own_opportunitycontactrole",
                                "owner_field": "created_by",
                                "intermediate_model": "OpportunityContactRole",
                                "intermediate_field": "contact",
                                "parent_field": "opportunity",
                                "attrs": """
                                    hx-get="{get_opportunity_contact_role_edit_url}"
                                    hx-target="#modalBox"
                                    hx-swap="innerHTML"
                                    onclick="event.stopPropagation();openModal()"
                                    hx-indicator="#modalBox"
                                    """,
                            },
                            {
                                "action": "Delete",
                                "src": "assets/icons/a4.svg",
                                "img_class": "w-4 h-4",
                                "permission": "opportunities.delete_opportunitycontactrole",
                                "attrs": """
                                        hx-post="{get_opportunity_contact_role_delete_url}"
                                        hx-target="#deleteModeBox"
                                        hx-swap="innerHTML"
                                        hx-trigger="click"
                                        hx-vals='{{"check_dependencies": "true"}}'
                                        onclick="openDeleteModeModal()"
                                        """,
                            },
                        ],
                        "col_attrs": contact_col_attrs,
                    },
                },
            },
        }
        add_perm = (
            is_owner(Opportunity, pk)
            and self.request.user.has_perm("opportunities.change_own_opportunity")
        ) or self.request.user.has_perm("opportunities.change_opportunity")
        if OpportunitySettings.is_team_selling_enabled():
            custom_buttons = []
            if (
                self.request.user.has_perm("opportunities.add_opportunityteammember")
                and add_perm
            ):
                custom_buttons.extend(
                    [
                        {
                            "label": _("Add Team"),
                            "url": reverse_lazy("opportunities:add_default_team"),
                            "attrs": """
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            hx-indicator="#modalBox"
                        """,
                            "icon": "fa-solid fa-users",
                            "class": "text-xs px-4 py-1.5 bg-primary-600 rounded-md hover:bg-primary-800 transition duration-300 text-white",
                        },
                        {
                            "label": _("Add Members"),
                            "url": reverse_lazy("opportunities:add_opportunity_member"),
                            "attrs": """
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            hx-indicator="#modalBox"
                        """,
                            "icon": "fa-solid fa-user-plus",
                            "class": "text-xs px-4 py-1.5 bg-white border border-primary-600 text-primary-600 rounded-md hover:bg-primary-50 transition duration-300",
                        },
                    ]
                )
            config["opportunity_team_members"] = {
                "title": "Opportunity Team",
                "columns": [
                    (
                        self.model._meta.get_field("opportunity_team_members")
                        .related_model._meta.get_field("user")
                        .verbose_name,
                        "user",
                    ),
                    (
                        self.model._meta.get_field("opportunity_team_members")
                        .related_model._meta.get_field("team_role")
                        .verbose_name,
                        "get_team_role_display",
                    ),
                ],
                "can_add": False,
                "custom_buttons": custom_buttons,
                "actions": [
                    {
                        "action": "Edit",
                        "src": "/assets/icons/edit.svg",
                        "img_class": "w-4 h-4",
                        "permission": "opportunities.change_opportunityteammember",
                        "attrs": """
                                    hx-get="{get_edit_url}"
                                    hx-target="#modalBox"
                                    hx-swap="innerHTML"
                                    onclick="event.stopPropagation();openModal()"
                                    hx-indicator="#modalBox"
                                    """,
                    },
                    {
                        "action": "Delete",
                        "src": "/assets/icons/a4.svg",
                        "img_class": "w-4 h-4",
                        "permission": "opportunities.delete_opportunityteammember",
                        "attrs": """
                                    hx-post="{get_delete_url}"
                                    hx-target="#deleteModeBox"
                                    hx-swap="innerHTML"
                                    hx-trigger="click"
                                    hx-vals='{{"check_dependencies": "true"}}'
                                    onclick="openDeleteModeModal()"
                                    """,
                    },
                ],
            }
            if OpportunitySettings.is_split_enabled():
                splits_custom_buttons = []
                if (
                    self.request.user.has_perm("opportunities.add_opportunitysplit")
                    and add_perm
                ):
                    splits_custom_buttons.append(
                        {
                            "label": _("Manage Opportunity Splits"),
                            "url": reverse_lazy(
                                "opportunities:manage_opportunity_splits"
                            ),
                            "attrs": """
                            hx-target="#contentModalBox"
                            hx-swap="innerHTML"
                            onclick="openContentModal()"
                        """,
                            "class": "text-xs px-4 py-1.5 bg-primary-600 rounded-md hover:bg-primary-800 transition duration-300 text-white",
                        }
                    )
                config["splits"] = {
                    "title": _("Opportunity Splits"),
                    "columns": [
                        (
                            self.model._meta.get_field("splits")
                            .related_model._meta.get_field("user")
                            .verbose_name,
                            "user",
                        ),
                        (
                            self.model._meta.get_field("splits")
                            .related_model._meta.get_field("split_type")
                            .verbose_name,
                            "split_type",
                        ),
                        (
                            self.model._meta.get_field("splits")
                            .related_model._meta.get_field("split_percentage")
                            .verbose_name,
                            "split_percentage",
                        ),
                        (
                            self.model._meta.get_field("splits")
                            .related_model._meta.get_field("split_amount")
                            .verbose_name,
                            "split_amount",
                        ),
                    ],
                    "can_add": False,
                    "custom_buttons": splits_custom_buttons,
                }
                if self.request.user.has_perm("opportunities.delete_opportunitysplit"):
                    config["splits"]["action_method"] = "actions"

        return config

    def get_excluded_related_lists(self):
        """
        Dynamically determine which related lists to exclude based on settings
        """
        excluded = ["contact_roles"]

        # If Team Selling is DISABLED, exclude opportunity_team_members from showing
        if not OpportunitySettings.is_team_selling_enabled():
            excluded.append("opportunity_team_members")
        if not OpportunitySettings.is_split_enabled():
            excluded.append("splits")

        return excluded

    @property
    def excluded_related_lists(self):
        """Property wrapper for excluded_related_lists."""
        return self.get_excluded_related_lists()


@method_decorator(htmx_required, name="dispatch")
class OpportunityContactRoleFormview(LoginRequiredMixin, HorillaSingleFormView):
    """Form view for creating and editing opportunity contact roles."""

    model = OpportunityContactRole
    fields = ["is_primary", "role", "contact", "opportunity"]
    full_width_fields = ["is_primary", "role", "contact"]
    modal_height = False
    form_title = _("Add Contact Role")
    hidden_fields = ["opportunity"]
    save_and_new = False

    def form_valid(self, form):
        """Handle form validation and create contact-account relationship."""
        super().form_valid(form)
        opportunity_contact_role = form.instance
        contact = opportunity_contact_role.contact
        opportunity = opportunity_contact_role.opportunity
        role = opportunity_contact_role.role

        # Automatically create related ContactAccountRelationship
        if opportunity.account:
            ContactAccountRelationship.objects.get_or_create(
                contact=contact,
                account=opportunity.account,
                defaults={"role": role},
                company=self.request.active_company,
            )

        return HttpResponse(
            "<script>htmx.trigger('#tab-contact-btn', 'click');closeModal();</script>"
        )

    def get_initial(self):
        """Get initial form data with opportunity ID if provided."""
        initial = super().get_initial()
        obj_id = self.request.GET.get("id")
        if obj_id:
            initial["opportunity"] = obj_id
        return initial

    @cached_property
    def form_url(self):
        """Return form URL for create or update view."""
        if self.kwargs.get("pk"):
            return reverse_lazy(
                "opportunities:edit_opportunity_contact_role",
                kwargs={"pk": self.kwargs.get("pk")},
            )
        return reverse_lazy("opportunities:add_opportunity_contact_role")

    def get(self, request, *args, **kwargs):

        opportunity_id = request.GET.get("id")
        if request.user.has_perm(
            "opportunities.change_opportunitycontactrole"
        ) or request.user.has_perm("opportunities.add_opportunitycontactrole"):
            return super().get(request, *args, **kwargs)

        if opportunity_id:
            opportunity = get_object_or_404(Opportunity, pk=opportunity_id)
            if opportunity.owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "error/403.html")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("accounts.delete_opportunitycontactrole", modal=True),
    name="dispatch",
)
class OpportunityContactRoleDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for Opportunity Contact Role
    """

    model = OpportunityContactRole

    def get_post_delete_response(self):
        return HttpResponse(
            "<script>htmx.trigger('#tab-contact-btn','click');</script>"
        )
