"""
Accounts Views Module

Django views for managing accounts in Horilla CRM.
Handles listing, creating, updating, deleting, and viewing accounts with
kanban and tabular displays. Supports child accounts, contact/partner relationships,
and HTMX for dynamic rendering.
Secured with permission checks and integrated with Horilla generic views.

Dependencies:
- Django authentication
- HTMX
- Horilla CRM models
- Horilla generic views
"""

# Standard library imports
import logging
from functools import cached_property
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView, View

# First-party / Horilla imports
from horilla_activity.views import HorillaActivitySectionView
from horilla_core.decorators import (
    htmx_required,
    permission_required,
    permission_required_or_denied,
)
from horilla_core.utils import is_owner
from horilla_crm.accounts.filters import AccountFilter
from horilla_crm.accounts.forms import (
    AccountFormClass,
    AccountSingleForm,
    AddChildAccountForm,
)
from horilla_crm.accounts.models import Account, PartnerAccountRelationship
from horilla_crm.contacts.models import ContactAccountRelationship
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

logger = logging.getLogger(__name__)


class AccountView(LoginRequiredMixin, HorillaView):
    """
    Render the accounts page
    """

    nav_url = reverse_lazy("accounts:accounts_nav_view")
    list_url = reverse_lazy("accounts:accounts_list_view")
    kanban_url = reverse_lazy("accounts:accounts_kanban_view")


@method_decorator(
    [
        htmx_required,
        permission_required(["accounts.view_account", "accounts.view_own_account"]),
    ],
    name="dispatch",
)
class AccountsNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar View for accounts page
    """

    nav_title = Account._meta.verbose_name_plural
    search_url = reverse_lazy("accounts:accounts_list_view")
    main_url = reverse_lazy("accounts:accounts_view")
    kanban_url = reverse_lazy("accounts:accounts_kanban_view")
    model_name = "Account"
    model_app_label = "accounts"
    filterset_class = AccountFilter
    exclude_kanban_fields = "company"
    enable_actions = True

    @cached_property
    def new_button(self):
        """Return the 'New Account' button if the user has add permission."""
        if self.request.user.has_perm(
            "accounts.add_account"
        ) or self.request.user.has_perm("accounts.add_own_account"):
            return {
                "url": f"""{ reverse_lazy('accounts:account_create_form_view')}?new=true""",
                "attrs": {"id": "account-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountListView(LoginRequiredMixin, HorillaListView):
    """
    account List view
    """

    model = Account
    view_id = "accounts-list"
    filterset_class = AccountFilter
    search_url = reverse_lazy("accounts:accounts_list_view")
    main_url = reverse_lazy("accounts:accounts_view")

    def no_record_add_button(self):
        """Return the 'New Account' button if the user has add permission."""
        if self.request.user.has_perm(
            "accounts.add_account"
        ) or self.request.user.has_perm("accounts.add_own_account"):
            return {
                "url": f"""{reverse_lazy('accounts:account_create_form_view') }?new=true""",
                "attrs": 'id="account-create"',
            }
        return None

    columns = [
        "name",
        "account_number",
        "account_owner",
        "account_type",
        "account_source",
        "annual_revenue",
    ]

    @cached_property
    def col_attrs(self):
        """Return column attributes for HTMX interactions if the user can view accounts."""
        query_params = self.request.GET.dict()
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
            "permission": "accounts.view_account",
            "own_permission": "accounts.view_own_account",
            "owner_field": "account_owner",
        }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]

    bulk_update_fields = ["account_type", "account_owner", "account_source", "industry"]

    acc_permissions = {
        "permission": "accounts.change_account",
        "own_permission": "accounts.change_own_account",
        "owner_field": "account_owner",
    }
    actions = [
        {
            **acc_permissions,
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
            **acc_permissions,
            "action": _("Change Owner"),
            "src": "assets/icons/a2.svg",
            "img_class": "w-4 h-4",
            "attrs": """
                        hx-get="{get_change_owner_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "accounts.delete_account",
            "own_permission": "accounts.delete_own_account",
            "owner_field": "account_owner",
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
            "permission": "accounts.add_account",
            "own_permission": "accounts.add_own_account",
            "owner_field": "account_owner",
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
    permission_required_or_denied("accounts.delete_account", modal=True),
    name="dispatch",
)
class AccountDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for account
    """

    model = Account

    def get_post_delete_response(self):
        return HttpResponse("<script>htmx.trigger('#reloadButton','click');</script>")


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountsKanbanView(LoginRequiredMixin, HorillaKanbanView):
    """
    Kanban view for account
    """

    model = Account
    view_id = "account-kanban"
    filterset_class = AccountFilter
    search_url = reverse_lazy("accounts:accounts_list_view")
    main_url = reverse_lazy("accounts:accounts_view")
    group_by_field = "account_type"

    columns = [
        "name",
        "account_number",
        "account_owner",
        "account_type",
        "account_source",
        "annual_revenue",
    ]

    actions = AccountListView.actions

    def no_record_add_button(self):
        """Return the 'New Account' button if the user has add permission."""
        if self.request.user.has_perm("accounts.add_account"):
            return {
                "url": f"""{ reverse_lazy('accounts:account_create')}?new=true""",
                "attrs": 'id="account-create"',
            }
        return None

    @cached_property
    def kanban_attrs(self):
        """Return kanban card attributes for HTMX interactions if the user can view accounts."""

        # Build query params
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
            "permission": "accounts.view_account",
            "own_permission": "accounts.view_own_account",
            "owner_field": "account_owner",
        }


@method_decorator(htmx_required, name="dispatch")
class AccountFormView(LoginRequiredMixin, HorillaMultiStepFormView):
    """
    form view for account
    """

    form_class = AccountFormClass
    model = Account
    fullwidth_fields = ["description"]
    detail_url_name = "accounts:account_detail_view"
    total_steps = 4
    step_titles = {
        "1": _("Account Information"),
        "2": _("Address Information"),
        "3": _("Additional Information"),
        "4": _("Description"),
    }

    single_step_url_name = {
        "create": "accounts:account_single_create_form_view",
        "edit": "accounts:account_single_edit_form_view",
    }

    @cached_property
    def form_url(self):
        """Return the URL for the account form (edit if PK exists, else create)."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("accounts:account_edit_form_view", kwargs={"pk": pk})
        return reverse_lazy("accounts:account_create_form_view")


@method_decorator(htmx_required, name="dispatch")
class AccountsSingleFormView(LoginRequiredMixin, HorillaSingleFormView):
    """Account Create/Update Single Page View"""

    model = Account
    form_class = AccountSingleForm
    full_width_fields = ["description"]
    detail_url_name = "accounts:account_detail_view"

    multi_step_url_name = {
        "create": "accounts:account_create_form_view",
        "edit": "accounts:account_edit_form_view",
    }

    @cached_property
    def form_url(self):
        """Form URL for lead"""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "accounts:account_single_edit_form_view", kwargs={"pk": pk}
            )
        return reverse_lazy("accounts:account_single_create_form_view")


@method_decorator(htmx_required, name="dispatch")
class AccountChangeOwnerForm(LoginRequiredMixin, HorillaSingleFormView):
    """
    Change owner form
    """

    model = Account
    fields = ["account_owner"]
    full_width_fields = ["account_owner"]
    modal_height = False
    form_title = _("Change Owner")

    @cached_property
    def form_url(self):
        """Return the URL for the account form (edit if PK exists, else create)."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("accounts:account_change_owner", kwargs={"pk": pk})
        return None

    def get(self, request, *args, **kwargs):

        account_id = self.kwargs.get("pk")
        if account_id:
            account = get_object_or_404(Account, pk=account_id)
            if account.account_owner == request.user:
                return super().get(request, *args, **kwargs)

        if request.user.has_perm("accounts.change_account") or request.user.has_perm(
            "accounts.add_account"
        ):
            return super().get(request, *args, **kwargs)

        return render(request, "error/403.html")


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountDetailView(RecentlyViewedMixin, LoginRequiredMixin, HorillaDetailView):
    """
    Detail view for account
    """

    model = Account
    breadcrumbs = [
        ("People", "accounts:accounts_view"),
        ("Accounts", "accounts:accounts_view"),
    ]
    body = [
        "name",
        "account_owner",
        "account_source",
        "industry",
        "annual_revenue",
        "account_type",
    ]
    tab_url = reverse_lazy("accounts:account_detail_view_tabs")

    actions = AccountListView.actions


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountDetailViewTabs(LoginRequiredMixin, HorillaDetailTabView):
    """
    Tab Views for account detail view
    """

    def __init__(self, **kwargs):
        request = getattr(_thread_local, "request", None)
        self.request = request
        self.object_id = self.request.GET.get("object_id")
        super().__init__(**kwargs)

    urls = {
        "details": "accounts:account_details_tab_view",
        "activity": "accounts:account_activity_tab_view",
        "related_lists": "accounts:account_related_list_tab_view",
        "notes_attachments": "accounts:account_notes_attachements",
        "history": "accounts:account_history_tab_view",
    }


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountDetailsTab(LoginRequiredMixin, HorillaDetailSectionView):
    """
    Details Tab view of account detail view
    """

    model = Account

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.excluded_fields.append("account_owner")


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountActivityTab(LoginRequiredMixin, HorillaActivitySectionView):
    """
    account detain view activity tab
    """

    model = Account


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountHistoryTab(LoginRequiredMixin, HorillaHistorySectionView):
    """
    History tab foe account detail view
    """

    model = Account


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountRelatedListsTab(LoginRequiredMixin, HorillaRelatedListSectionView):
    """
    Related list tab view
    """

    model = Account

    @cached_property
    def related_list_config(self):
        """
        Return configuration for related lists (child accounts, contacts, partners)
        with columns, actions, and add URLs.
        """
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        pk = self.request.GET.get("object_id")
        referrer_url = "account_detail_view"
        opportunity_model = self.model._meta.get_field(
            "opportunity_account"
        ).related_model
        contact_custom_buttons = []
        if self.request.user.has_perm("contacts.add_contact"):
            contact_custom_buttons.append(
                {
                    "label": _("New Contact"),
                    "url": reverse_lazy("contacts:related_account_contact_create_form"),
                    "attrs": """
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            hx-indicator="#modalBox"
                        """,
                    "icon": "fa-solid fa-user-plus",
                    "class": "text-xs px-4 py-1.5 bg-primary-600 rounded-md hover:bg-primary-800 transition duration-300 text-white",
                }
            )

        if self.request.user.has_perm("accounts.add_contactaccountrelationship"):
            contact_custom_buttons.append(
                {
                    "label": _("Add Relationship"),
                    "url": reverse_lazy("accounts:create_account_contact_relation"),
                    "attrs": """
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            hx-indicator="#modalBox"
                        """,
                    "icon": "fa-solid fa-users",
                    "class": "text-xs px-4 py-1.5 bg-white border border-primary-600 text-primary-600 rounded-md hover:bg-primary-50 transition duration-300",
                }
            )

        return {
            "custom_related_lists": {
                "contact_relationships": {
                    "app_label": "contacts",
                    "model_name": "Contact",
                    "intermediate_model": "ContactAccountRelationship",
                    "intermediate_field": "contact",
                    "related_field": "account",
                    "config": {
                        "title": _("Related Contacts"),
                        "columns": [
                            (
                                ContactAccountRelationship._meta.get_field("contact")
                                .related_model._meta.get_field("first_name")
                                .verbose_name,
                                "first_name",
                            ),
                            (
                                ContactAccountRelationship._meta.get_field("contact")
                                .related_model._meta.get_field("last_name")
                                .verbose_name,
                                "last_name",
                            ),
                            (
                                ContactAccountRelationship._meta.get_field(
                                    "role"
                                ).verbose_name,
                                "account_relationships__role",
                            ),
                        ],
                        "custom_buttons": contact_custom_buttons,
                        "col_attrs": [
                            {
                                "title": {
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
                        ],
                        "actions": [
                            (
                                {
                                    "permission": "contacts.change_contactaccountrelationship",
                                    "own_permission": "contacts.change_own_contactaccountrelationship",
                                    "owner_field": "created_by",
                                    "intermediate_model": "ContactAccountRelationship",
                                    "intermediate_field": "contact",
                                    "parent_field": "account",
                                    "action": _("Edit"),
                                    "src": "assets/icons/edit.svg",
                                    "img_class": "w-4 h-4",
                                    "attrs": """
                                            hx-get="{get_edit_account_contact_relation_url}?new=true"
                                            hx-target="#modalBox"
                                            hx-swap="innerHTML"
                                            onclick="openModal()"
                                            """,
                                }
                            ),
                            (
                                {
                                    "permission": "contacts.delete_contactaccountrelationship",
                                    "action": "Delete",
                                    "src": "assets/icons/a4.svg",
                                    "img_class": "w-4 h-4",
                                    "attrs": """
                                                hx-post="{get_delete_related_contact_url}"
                                                hx-target="#deleteModeBox"
                                                hx-swap="innerHTML"
                                                hx-trigger="click"
                                                hx-vals='{{"check_dependencies": "true"}}'
                                                onclick="openDeleteModeModal()"
                                            """,
                                }
                            ),
                        ],
                    },
                },
                "partner": {
                    "app_label": "accounts",
                    "model_name": "Account",
                    "intermediate_model": "PartnerAccountRelationship",
                    "intermediate_field": "partner",
                    "related_field": "account",
                    "config": {
                        "title": _("Partner"),
                        "can_add": self.request.user.has_perm(
                            "accounts.add_partneraccountrelationship"
                        ),
                        "add_url": reverse_lazy("accounts:account_partner_create_form"),
                        "columns": [
                            (
                                PartnerAccountRelationship._meta.get_field("partner")
                                .related_model._meta.get_field("name")
                                .verbose_name,
                                "name",
                            ),
                            (
                                PartnerAccountRelationship._meta.get_field("partner")
                                .related_model._meta.get_field("annual_revenue")
                                .verbose_name,
                                "annual_revenue",
                            ),
                            (
                                PartnerAccountRelationship._meta.get_field(
                                    "role"
                                ).verbose_name,
                                "partner__role",
                            ),
                        ],
                        "col_attrs": [
                            {
                                "name": {
                                    "hx-get": f"{{get_detail_url}}?referrer_app={self.model._meta.app_label}&referrer_model={self.model._meta.model_name}&referrer_id={pk}&referrer_url={referrer_url}&{query_string}",
                                    "hx-target": "#mainContent",
                                    "hx-swap": "outerHTML",
                                    "hx-push-url": "true",
                                    "hx-select": "#mainContent",
                                    "permission": "accounts.view_account",
                                    "own_permission": "accounts.view_own_account",
                                    "owner_field": "account_owner",
                                }
                            }
                        ],
                        "actions": [
                            (
                                {
                                    "action": _("Edit"),
                                    "src": "assets/icons/edit.svg",
                                    "img_class": "w-4 h-4",
                                    "permission": "accounts.change_partneraccountrelationship",
                                    "own_permission": "accounts.change_own_partneraccountrelationship",
                                    "owner_field": "created_by",
                                    "intermediate_model": "PartnerAccountRelationship",
                                    "intermediate_field": "partner",
                                    "parent_field": "account",
                                    "attrs": """
                                            hx-get="{get_account_partner_url}?new=true"
                                            hx-target="#modalBox"
                                            hx-swap="innerHTML"
                                            onclick="openModal()"
                                            """,
                                }
                            ),
                            (
                                {
                                    "action": "Delete",
                                    "src": "assets/icons/a4.svg",
                                    "img_class": "w-4 h-4",
                                    "permission": "accounts.delete_partneraccountrelationship",
                                    "attrs": """
                                            hx-post="{get_account_partner_delete_url}"
                                            hx-target="#deleteModeBox"
                                            hx-swap="innerHTML"
                                            hx-trigger="click"
                                            hx-vals='{{"check_dependencies": "true"}}'
                                            onclick="openDeleteModeModal()"
                                            """,
                                }
                            ),
                        ],
                    },
                },
            },
            "child_accounts": {
                "title": _("Child Accounts"),
                "can_add": (
                    is_owner(Account, pk)
                    and self.request.user.has_perm("accounts.change_account")
                )
                or self.request.user.has_perm("accounts.chang_own_account"),
                "add_url": reverse_lazy("accounts:create_child_accounts"),
                "columns": [
                    (Account._meta.get_field("name").verbose_name, "name"),
                    (
                        Account._meta.get_field("account_type").verbose_name,
                        "get_account_type_display",
                    ),
                    (
                        Account._meta.get_field("annual_revenue").verbose_name,
                        "annual_revenue",
                    ),
                ],
                "col_attrs": [
                    {
                        "name": {
                            "hx-get": f"{{get_detail_url}}?referrer_app={self.model._meta.app_label}&referrer_model={self.model._meta.model_name}&referrer_id={pk}&referrer_url={referrer_url}&{query_string}",
                            "hx-target": "#mainContent",
                            "hx-swap": "outerHTML",
                            "hx-push-url": "true",
                            "hx-select": "#mainContent",
                            "permission": "accounts.view_account",
                            "own_permission": "accounts.view_own_account",
                            "owner_field": "account_owner",
                        }
                    }
                ],
                "actions": [
                    (
                        {
                            "action": "delete",
                            "src": "/assets/icons/a4.svg",
                            "img_class": "w-4 h-4",
                            "permission": "accounts.delete_account",
                            "attrs": """
                                    hx-delete="{get_child_account_url}"
                                    hx-on:click="hxConfirm(this,'Are you sure you want to remove this child account relationship?')"
                                    hx-target="#deleteModeBox"
                                    hx-swap="innerHTML"
                                    hx-trigger="confirmed"
                                    """,
                        }
                    ),
                ],
            },
            "opportunity_account": {
                "title": _("Opportunities"),
                "can_add": self.request.user.has_perm("opportunities.add_opportunity"),
                "add_url": reverse_lazy("opportunities:opportunity_create"),
                "columns": [
                    (
                        opportunity_model._meta.get_field("name").verbose_name,
                        "name",
                    ),
                    (
                        opportunity_model._meta.get_field("amount").verbose_name,
                        "amount",
                    ),
                    (
                        opportunity_model._meta.get_field("stage").verbose_name,
                        "stage__name",
                    ),
                    (
                        opportunity_model._meta.get_field("close_date").verbose_name,
                        "close_date",
                    ),
                ],
                "col_attrs": [
                    {
                        "name": {
                            "hx-get": f"{{get_detail_url}}?referrer_app={self.model._meta.app_label}&referrer_model={self.model._meta.model_name}&referrer_id={pk}&referrer_url={referrer_url}&{query_string}",
                            "hx-target": "#mainContent",
                            "hx-swap": "outerHTML",
                            "hx-push-url": "true",
                            "hx-select": "#mainContent",
                            "style": "cursor:pointer",
                            "class": "hover:text-primary-600",
                        }
                    }
                ],
                "actions": [
                    (
                        {
                            "action": _("Edit"),
                            "src": "assets/icons/edit.svg",
                            "img_class": "w-4 h-4",
                            "permission": "opportunities.change_opportunity",
                            "own_permission": "opportunities.change_own_opportunity",
                            "owner_field": "owner",
                            "attrs": """
                                hx-get="{get_edit_url}?new=true"
                                hx-target="#modalBox"
                                hx-swap="innerHTML"
                                onclick="openModal()"
                                """,
                        }
                    ),
                    (
                        {
                            "action": "Delete",
                            "src": "assets/icons/a4.svg",
                            "img_class": "w-4 h-4",
                            "permission": "opportunities.delete_opportunity",
                            "attrs": """
                                    hx-post="{get_delete_url}"
                                    hx-target="#deleteModeBox"
                                    hx-swap="innerHTML"
                                    hx-trigger="click"
                                    hx-vals='{{"check_dependencies": "true"}}'
                                    onclick="openDeleteModeModal()"
                                """,
                        }
                    ),
                ],
            },
        }

    excluded_related_lists = ["contact_relationships", "partner_account", "partner"]


@method_decorator(
    permission_required_or_denied(
        ["accounts.view_account", "accounts.view_own_account"]
    ),
    name="dispatch",
)
class AccountsNotesAndAttachments(
    LoginRequiredMixin, HorillaNotesAttachementSectionView
):
    """Notes and attachments section for Account objects."""

    model = Account


@method_decorator(htmx_required, name="dispatch")
class AddRelatedContactFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Create and update form for adding related accounts into contacts
    """

    model = ContactAccountRelationship
    modal_height = False
    fields = ["contact", "account", "role"]
    form_title = _("Add Contact Relationships")
    full_width_fields = ["account", "contact", "role"]
    hidden_fields = ["account"]
    save_and_new = False

    def get(self, request, *args, **kwargs):

        account_id = request.GET.get("id")
        if request.user.has_perm(
            "accounts.change_contactaccountrelationship"
        ) or request.user.has_perm("accounts.add_contactaccountrelationship"):
            return super().get(request, *args, **kwargs)

        if account_id:
            account = get_object_or_404(Account, pk=account_id)

            if account.account_owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "error/403.html")

    def form_valid(self, form):
        super().form_valid(form)
        return HttpResponse(
            "<script>htmx.trigger('#tab-contact_relationships-btn', 'click');closeModal();</script>"
        )

    def get_initial(self):
        initial = super().get_initial()
        obj_id = self.request.GET.get("id")
        if obj_id:
            initial["account"] = obj_id
        return initial

    @cached_property
    def form_url(self):
        """
        Return the URL for the contact-account relationship form
        (edit if PK exists, else create).
        """
        if self.kwargs.get("pk"):
            return reverse_lazy(
                "accounts:edit_account_contact_relation",
                kwargs={"pk": self.kwargs.get("pk")},
            )
        return reverse_lazy("accounts:create_account_contact_relation")


@method_decorator(htmx_required, name="dispatch")
class AddChildAccountFormView(LoginRequiredMixin, FormView):
    """
    Form view to select an existing account and assign it as a child account.
    """

    template_name = "single_form_view.html"
    form_class = AddChildAccountForm
    header = True

    def get(self, request, *args, **kwargs):

        account_id = request.GET.get("id")
        if request.user.has_perm("accounts.change_account") or request.user.has_perm(
            "accounts.add_account"
        ):
            return super().get(request, *args, **kwargs)

        if account_id:
            try:
                account = get_object_or_404(Account, pk=account_id)
            except Http404:
                messages.error(request, "Account not found or no longer exists.")
                return HttpResponse(
                    "<script>$('#reloadButton').click();closeModal();</script>"
                )
            if account.account_owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "error/403.html")

    def get_form_kwargs(self):
        """
        Pass the request to the form for queryset filtering and validation.
        """
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def get_initial(self):
        """
        Prepopulate the form with initial data if needed.
        """
        initial = super().get_initial()
        parent_id = self.request.GET.get("id")

        if parent_id:
            try:
                parent_account = Account.objects.get(pk=parent_id)
                initial["parent_account"] = parent_account
            except Account.DoesNotExist:
                logger.error("Parent account with ID %s not found", parent_id)

        return initial

    def get_context_data(self, **kwargs):
        """
        Add context data for the template.
        """
        context = super().get_context_data(**kwargs)
        context["form_title"] = _("Add Child Account")
        context["full_width_fields"] = ["account"]
        form_url = self.get_form_url()
        context["form_url"] = form_url
        context["modal_height"] = False
        context["view_id"] = "add-child-account-form-view"
        context["condition_fields"] = []
        context["header"] = self.header
        context["field_permissions"] = {}
        context["hx_attrs"] = {
            "hx-post": str(form_url),
            "hx-target": "#modalBox",
            "hx-swap": "innerHTML",
        }

        return context

    def form_valid(self, form):
        """Update the selected account's parent_account field and return HTMX response."""
        response = None

        if not self.request.user.is_authenticated:
            messages.error(
                self.request, _("You must be logged in to perform this action.")
            )
            response = self.form_invalid(form)
        else:
            selected_account = form.cleaned_data["account"]
            parent_account = form.cleaned_data["parent_account"]

            if not parent_account:
                form.add_error(None, _("No parent account specified in the request."))
                response = self.form_invalid(form)
            else:
                try:
                    if selected_account.id == parent_account.id:
                        form.add_error(
                            "account", _("An account cannot be its own parent.")
                        )
                        response = self.form_invalid(form)
                    elif selected_account.parent_account:
                        form.add_error(
                            "account", _("This account already has a parent account.")
                        )
                        response = self.form_invalid(form)
                    else:
                        # Update the selected account
                        selected_account.parent_account = parent_account
                        selected_account.updated_at = timezone.now()
                        selected_account.updated_by = self.request.user
                        selected_account.company = self.request.active_company
                        selected_account.save()
                        messages.success(
                            self.request, _("Child account assigned successfully!")
                        )
                        response = HttpResponse(
                            "<script>htmx.trigger('#tab-child_accounts-btn', 'click');closeModal();</script>"
                        )
                except ValueError:
                    form.add_error(None, _("Invalid parent account ID format."))
                    response = self.form_invalid(form)
                except Exception:
                    form.add_error(
                        None,
                        _(
                            "An unexpected error occurred while assigning the child account."
                        ),
                    )
                    response = self.form_invalid(form)

        return response

    def get_form_url(self):
        """
        Get the form URL for submission.
        """
        if self.kwargs.get("pk"):
            return reverse_lazy(
                "accounts:edit_child_account", kwargs={"pk": self.kwargs.get("pk")}
            )
        return reverse_lazy("accounts:create_child_accounts")


@method_decorator(htmx_required, name="dispatch")
class AccountPartnerFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    create and update from view for Account partner
    """

    model = PartnerAccountRelationship
    fields = ["partner", "role", "account"]
    full_width_fields = ["partner", "role", "account"]
    modal_height = False
    form_title = _("Account Partner")
    hidden_fields = ["account"]
    save_and_new = False

    def get(self, request, *args, **kwargs):

        account_id = request.GET.get("id")
        if request.user.has_perm(
            "accounts.change_partneraccountrelationship"
        ) or request.user.has_perm("accounts.add_partneraccountrelationship"):
            return super().get(request, *args, **kwargs)

        if account_id:
            account = get_object_or_404(Account, pk=account_id)
            if account.account_owner == request.user:
                return super().get(request, *args, **kwargs)

        return render(request, "error/403.html")

    def form_valid(self, form):
        account = form.cleaned_data.get("account")
        role = form.cleaned_data.get("role")

        existing = PartnerAccountRelationship.objects.filter(account=account, role=role)
        if self.object:  # If update, exclude current instance
            existing = existing.exclude(pk=self.object.pk)

        super().form_valid(form)
        return HttpResponse(
            "<script>htmx.trigger('#tab-partner-btn','click');closeModal();</script>"
        )

    def get_initial(self):
        """Set initial form data for the account form."""
        initial = super().get_initial()
        obj_id = self.request.GET.get("id")
        if obj_id:
            initial["account"] = obj_id
        return initial

    @cached_property
    def form_url(self):
        """
        Return the URL for the account partner form
        (edit if PK exists, else create).
        """
        if self.kwargs.get("pk"):
            return reverse_lazy(
                "accounts:account_partner_update_form",
                kwargs={"pk": self.kwargs.get("pk")},
            )
        return reverse_lazy("accounts:account_partner_create_form")


@method_decorator(htmx_required, name="dispatch")
class ChildAccountDeleteView(LoginRequiredMixin, View):
    """
    View to remove parent-child relationship from a account.
    """

    def delete(self, request, pk, *args, **kwargs):
        """
        Handle DELETE request to remove parent account relationship.
        """
        child_account = get_object_or_404(Account, pk=pk)

        has_permission = (
            request.user.has_perm("accounts.change_account")
            or child_account.account_owner == request.user
            or (
                child_account.parent_account
                and child_account.parent_account.account_owner == request.user
            )
        )

        if not has_permission:
            messages.error(
                request, _("You don't have permission to perform this action.")
            )
            return HttpResponse(
                "<script>htmx.trigger('#tab-child_accounts-btn', 'click');</script>"
            )

        parent_account = child_account.parent_account

        if not parent_account:
            messages.warning(request, _("This contact doesn't have a parent account."))
            return HttpResponse(
                "<script>htmx.trigger('#tab-child_accounts-btn', 'click');</script>"
            )

        try:
            child_account.parent_account = None
            child_account.updated_at = timezone.now()
            child_account.updated_by = request.user
            child_account.save()

            messages.success(
                request,
                _(
                    f"Successfully removed {child_account} from {parent_account}'s child accounts."
                ),
            )

            return HttpResponse(
                "<script>htmx.trigger('#tab-child_accounts-btn', 'click');</script>"
            )

        except Exception:
            messages.error(
                request, _("An error occurred while removing the child account.")
            )
            return HttpResponse(
                "<script>htmx.trigger('#tab-child_accounts-btn', 'click');</script>"
            )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        "accounts.delete_partneraccountrelationship", modal=True
    ),
    name="dispatch",
)
class PartnerAccountDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for partner account
    """

    model = PartnerAccountRelationship

    def get_post_delete_response(self):
        return HttpResponse(
            "<script>htmx.trigger('#tab-partner-btn','click');</script>"
        )
