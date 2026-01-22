"""
Views related to Role management in Horilla Core.
"""

# Standard library imports
from functools import cached_property
from urllib.parse import urlencode

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import TemplateView

# First-party / Horilla imports
from horilla.auth.models import User
from horilla_core.decorators import htmx_required, permission_required_or_denied
from horilla_core.filters import UserFilter
from horilla_core.forms import AddUsersToRoleForm
from horilla_core.models import Role
from horilla_generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)
from horilla_utils.middlewares import _thread_local


@method_decorator(htmx_required, name="dispatch")
class AddRole(LoginRequiredMixin, HorillaSingleFormView):
    """
    View to create or edit a Role
    """

    model = Role
    fields = ["role_name", "parent_role", "description"]
    full_width_fields = ["role_name", "parent_role", "description"]
    modal_height = False
    # hidden_fields = ["parent_role"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = getattr(_thread_local, "request", None)
        role_id = request.GET.get("role_id")
        role_count = Role.objects.all().count()
        if role_id or role_count == 0:
            self.hidden_fields = ["parent_role"]

    @cached_property
    def form_url(self):
        """
        Determine the form URL based on whether editing or creating a role.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("horilla_core:edit_roles_view", kwargs={"pk": pk})
        return reverse_lazy("horilla_core:create_roles_view")

    def get(self, request, *args, **kwargs):
        """
        Handle GET request to display the role form.
        """
        pk = kwargs.get("pk")
        if pk:
            try:
                self.model.objects.get(pk=pk)
            except self.model.DoesNotExist:
                messages.error(request, "The requested role does not exist.")
                return HttpResponse("<script>$('#reloadButton').click();</script>")

        return super().get(request, *args, **kwargs)

    def get_initial(self):
        """
        Set initial data for the form, particularly the parent_role if provided.
        """
        initial = super().get_initial()
        role_id = self.request.GET.get("role_id")
        role = Role.objects.filter(pk=role_id).first()
        if role:
            initial["parent_role"] = role
        return initial


@method_decorator(htmx_required, name="dispatch")
class AddUserToRole(LoginRequiredMixin, HorillaSingleFormView):
    """
    View to add users to a Role
    """

    model = User
    form_class = AddUsersToRoleForm
    full_width_fields = ["role", "users"]
    modal_height = False
    form_url = reverse_lazy("horilla_core:add_user_to_roles_view")
    hidden_fields = ["role"]
    save_and_new = False

    def get_initial(self):
        """
        Set initial data for the form, particularly the role if provided.
        """
        initial = super().get_initial()
        role_id = self.request.GET.get("role_id")
        role = Role.objects.filter(pk=role_id).first()  # Get the first object or None
        if role:
            initial["role"] = role
        return initial

    def form_valid(self, form):
        """
        Handle valid form submission to add users to the role.
        """
        users = form.save(commit=True)
        messages.success(
            self.request,
            _(
                f"Successfully assigned {len(users)} user(s) to the role '{form.cleaned_data['role']}'."
            ),
        )
        return HttpResponse("<script>$('#reloadButton').click();closeModal();</script>")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.view_{User._meta.model_name}"
    ),
    name="dispatch",
)
class RoleUsersListView(LoginRequiredMixin, HorillaListView):
    """
    List view to display users in a specific role
    """

    model = User
    filterset_class = UserFilter
    table_width = False
    view_id = "user-roles"
    filter_url_push = False
    search_url = reverse_lazy("horilla_core:view_user_in_role_list_view")
    main_url = reverse_lazy("horilla_core:view_user_in_role")
    bulk_delete_enabled = False
    bulk_update_fields = ["role"]

    def get_queryset(self):
        """
        Filter the queryset to only include users in the specified role.
        """
        queryset = super().get_queryset()
        role_id = self.request.GET.get("role_id")
        queryset = queryset.filter(role=role_id)
        return queryset

    @cached_property
    def col_attrs(self):
        """
        Define column attributes, including HTMX attributes for interactivity.
        """
        query_params = self.request.GET.dict()
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        if self.request.user.has_perm(
            f"{User._meta.app_label}.view_{User._meta.model_name}"
        ):
            htmx_attrs = {
                "hx-get": f"{{get_detail_view_url}}?{query_string}",
                "hx-target": "#role-container",
                "hx-swap": "outerHTML",
                "hx-push-url": "true",
                "hx-select": "#users-view",
                "hx-on:click": "closeContentModal()",
            }
        return [
            {
                "get_avatar_with_name": {
                    "style": "cursor:pointer",
                    "class": "hover:text-primary-600",
                    **htmx_attrs,
                }
            }
        ]

    columns = [
        (_("Users"), "get_avatar_with_name"),
    ]
    actions = [
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "horilla_core.delete_role",
            "attrs": """
                hx-post="{get_delete_user_from_role}"
                hx-target="#deleteModeBox"
                hx-swap="innerHTML"
                hx-trigger="confirmed"
                hx-on:click="hxConfirm(this,'Are you sure you want to delete the user from this role?')"
                hx-on::after-request="$('#reloadMessagesButton').click();"
            """,
        }
    ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.view_{User._meta.model_name}"
    ),
    name="dispatch",
)
class UsersInRoleView(LoginRequiredMixin, TemplateView):
    """
    Detail view to display users in a specific role
    """

    template_name = "role/view_user.html"


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        f"{User._meta.app_label}.view_{User._meta.model_name}"
    ),
    name="dispatch",
)
class RoleUsersNavView(LoginRequiredMixin, HorillaNavView):
    """
    Nav view to display users in a specific role
    """

    search_url = reverse_lazy("horilla_core:view_user_in_role_list_view")
    main_url = reverse_lazy("horilla_core:view_user_in_role")
    filterset_class = UserFilter
    model_name = str(User.__name__)
    model_app_label = "horilla_core"
    nav_width = False
    gap_enabled = False
    all_view_types = False
    recently_viewed_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False
    navbar_indication = True

    def get_context_data(self, **kwargs):
        """
        Add role information to the context data.
        """
        context = super().get_context_data(**kwargs)
        role_id = self.request.GET.get("role_id")
        role = Role.objects.filter(pk=role_id).first()
        self.nav_title = role

        context["nav_title"] = self.nav_title
        return context

    def get_navbar_indication_attrs(self):

        return {"onclick": "closeContentModal()"}


@method_decorator(htmx_required, name="dispatch")
class DeleteUserFromRole(LoginRequiredMixin, View):
    """
    Remove role from a user (without deleting the user)
    """

    def post(self, request, *args, **kwargs):
        """
        Handle POST request to remove a user from a role.
        """
        user_id = kwargs.get("pk")
        try:
            user = get_object_or_404(User, pk=user_id)
        except Exception:
            messages.error(request, _("The requested user does not exist."))
            return HttpResponse(
                "<script>$('#reloadButton').click();closeDeleteModeModal();closeContentModal();</script>"
            )

        user.role = None
        user.save()

        messages.success(request, f"{user.username} removed from role")

        return HttpResponse(
            "<script>"
            "htmx.trigger('#reloadButton','click');"
            "closeDeleteModeModal();"
            "closeContentModal();"
            "</script>"
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.delete_role", modal=True),
    name="dispatch",
)
class RoleDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    View to delete a Role
    """

    model = Role

    def get_post_delete_response(self):
        """
        Handle post-delete response to refresh the role list.
        """
        return HttpResponse(
            "<script>$('#reloadButton').click();closeDeleteModeModal();</script>"
        )
