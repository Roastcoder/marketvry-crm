"""
Views for managing notes and attachments in Horilla, including listing, detail view, creation, and deletion of attachments.
These views handle permissions, rendering, and interactions for attachments related to various models in Horilla.
"""

# Standard library
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin

# Django / third-party imports
from django.views.generic import DetailView, FormView

from horilla.http import Http404, HttpResponse
from horilla.shortcuts import get_object_or_404, render

# First-party (Horilla)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla_core.models import HorillaAttachment, HorillaContentType
from horilla_generics.forms import HorillaAttachmentForm
from horilla_generics.views.delete import HorillaSingleDeleteView
from horilla_generics.views.details import HorillaModalDetailView
from horilla_generics.views.list import HorillaListView

logger = logging.getLogger(__name__)


class AttachmentListView(HorillaListView):
    """List view for displaying horilla attachments."""

    model = HorillaAttachment
    columns = ["title", "created_by", "created_at"]
    bulk_select_option = False
    list_column_visibility = False
    table_height_as_class = "h-[calc(_100vh_-_500px_)]"
    table_width = False


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "horilla_core.view_horillaattachment",
            "horilla_core.view_own_horillaattachment",
        ]
    ),
    name="dispatch",
)
class HorillaNotesAttachementSectionView(DetailView):
    """View for displaying notes and attachments section in detail views."""

    template_name = "notes_attachments.html"
    context_object_name = "obj"

    def get_actions(self):
        """
        Return actions based on user permissions.
        """

        actions = [
            {
                "action": "View",
                "src": "assets/icons/eye1.svg",
                "img_class": "w-4 h-4",
                "permissions": [
                    "horilla_core.view_horillaattachment",
                    "horilla_core.view_own_horillaattachment",
                ],
                "attrs": """
                            hx-get="{get_detail_view_url}"
                            hx-target="#contentModalBox"
                            hx-swap="innerHTML"
                            onclick="openContentModal()"
                            """,
            },
            {
                "action": "Edit",
                "src": "assets/icons/edit.svg",
                "img_class": "w-4 h-4",
                "permission": "horilla_core.change_horillaattachment",
                "own_permission": "horilla_core.change_own_horillaattachment",
                "owner_field": "created_by",
                "attrs": """
                            hx-get="{get_edit_url}"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            hx-on:click="openModal();"
                            """,
            },
            {
                "action": "Delete",
                "src": "assets/icons/a4.svg",
                "img_class": "w-4 h-4",
                "permission": "horilla_core.delete_horillaattachment",
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

        return actions

    def check_attachment_add_permission(self):
        """
        Check if user has permission to add attachments.
        Requires:
        1. Add permission on HorillaAttachment model
        2. Add or Change permission on the related object (or change_own if owner)

        Returns:
            bool: True if user has permission, False otherwise
        """
        user = self.request.user

        related_object = self.get_object()
        related_model = related_object.__class__
        model_name = related_model._meta.model_name
        app_label = related_model._meta.app_label

        # Check if user is the owner of the related object
        is_owner = False
        owner_fields = getattr(related_model, "OWNER_FIELDS", [])

        for owner_field in owner_fields:
            try:
                field_value = getattr(related_object, owner_field, None)
                if field_value:
                    # Handle ManyToMany fields
                    if hasattr(field_value, "all"):
                        if user in field_value.all():
                            is_owner = True
                            break
                    # Handle ForeignKey fields
                    elif field_value == user:
                        is_owner = True
                        break
            except Exception:
                continue

        if is_owner:
            change_own_perm = f"{app_label}.change_own_{model_name}"
            if user.has_perm(change_own_perm) and user.has_perm(
                "horilla_core.add_horillaattachment"
            ):
                return True

        change_perm = f"{app_label}.change_{model_name}"

        if user.has_perm(change_perm) and user.has_perm(
            "horilla_core.add_horillaattachment"
        ):
            return True

        return False

    def get(self, request, *args, **kwargs):
        """Load attachment list for the detail object and render with add-permission flag."""
        self.object = self.get_object()
        object_id = self.kwargs.get("pk")

        try:
            content_type = HorillaContentType.objects.get_for_model(model=self.model)
        except HorillaContentType.DoesNotExist:
            from horilla.http import HttpResponseNotFound

            return HttpResponseNotFound("Model not found")

        queryset = HorillaAttachment.objects.filter(
            content_type=content_type, object_id=object_id
        )

        # Store instance_ids in session for navigation
        ordered_ids_key = "ordered_ids_horillaattachment"
        ordered_ids = list(queryset.values_list("pk", flat=True))
        self.request.session[ordered_ids_key] = ordered_ids

        list_view = AttachmentListView()
        list_view.request = self.request
        list_view.queryset = queryset
        list_view.view_id = f"attachments_{content_type.model}_{object_id}"
        list_view.actions = self.get_actions()
        context = list_view.get_context_data(object_list=queryset)
        context.update(super().get_context_data())
        context["can_add_attachment"] = self.check_attachment_add_permission()
        return render(request, self.template_name, context)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "horilla_core.view_horillaattachment",
            "horilla_core.view_own_horillaattachment",
        ]
    ),
    name="dispatch",
)
class HorillaNotesAttachementDetailView(HorillaModalDetailView):
    """Detail view for displaying individual notes and attachments."""

    template_name = "notes_attachments_detail.html"
    model = HorillaAttachment
    title = "Notes and Attachment"

    def get(self, request, *args, **kwargs):
        """Load attachment detail or return error script if not found."""
        try:
            self.object = self.get_object()
        except Http404:
            messages.error(self.request, "The requested attachment does not exist.")
            return HttpResponse(
                "<script>$('#reloadButton').click();$('#reloadMessagesButton').click();closeContentModal();</script>"
            )

        context = self.get_context_data()
        return self.render_to_response(context)


@method_decorator(htmx_required, name="dispatch")
class HorillaNotesAttachmentCreateView(LoginRequiredMixin, FormView):
    """View for creating new notes and attachments."""

    template_name = "forms/notes_attachment_form.html"
    form_class = HorillaAttachmentForm
    model = HorillaAttachment

    def get_context_data(self, **kwargs):
        """Set form_url for create or edit based on pk."""
        context = super().get_context_data(**kwargs)
        context["form_url"] = reverse_lazy("horilla_generics:notes_attachment_create")
        pk = self.kwargs.get("pk")
        if pk:
            context["form_url"] = reverse_lazy(
                "horilla_generics:notes_attachment_edit", kwargs={"pk": pk}
            )
        return context

    def get_object(self):
        """Return object if pk exists (for edit mode)."""
        pk = self.kwargs.get("pk")
        if pk:
            obj = get_object_or_404(HorillaAttachment, pk=pk)
            return obj
        return None

    def get_form(self, form_class=None):
        """Bind instance if editing."""
        form_class = self.get_form_class()
        obj = self.get_object()
        return form_class(instance=obj, **self.get_form_kwargs())

    def check_related_object_permission(self, related_object, permission_type="add"):
        """
        Check if user has permission to add/change notes on the related object.

        Args:
            related_object: The object to which the attachment is related
            permission_type: 'add' or 'change'

        Returns:
            bool: True if user has permission, False otherwise
        """
        user = self.request.user

        related_model = related_object.__class__
        model_name = related_model._meta.model_name
        app_label = related_model._meta.app_label

        is_owner = False
        owner_fields = getattr(related_model, "OWNER_FIELDS", [])

        for owner_field in owner_fields:
            try:
                field_value = getattr(related_object, owner_field, None)
                if field_value:
                    if hasattr(field_value, "all"):
                        if user in field_value.all():
                            is_owner = True
                            break
                    # Handle ForeignKey fields
                    elif field_value == user:
                        is_owner = True
                        break
            except Exception:
                continue

        if is_owner:
            change_own_perm = f"{app_label}.change_own_{model_name}"
            if user.has_perm(change_own_perm) and user.has_perm(
                "horilla_core.add_horillaattachment"
            ):
                return True

        change_perm = f"{app_label}.change_{model_name}"
        if user.has_perm(change_perm) and user.has_perm(
            "horilla_core.add_horillaattachment"
        ):
            return True

        return False

    def dispatch(self, request, *args, **kwargs):
        """Check permissions before processing the request."""
        # For edit mode, check if attachment exists and user has permission
        pk = kwargs.get("pk")
        if pk:
            try:
                attachment = self.model.objects.get(pk=pk)
                related_object = attachment.related_object

                if related_object:
                    if not self.check_related_object_permission(
                        related_object, "change"
                    ):
                        messages.error(
                            request,
                            _("You don't have permission to edit this attachment."),
                        )
                        return HttpResponse(
                            "<script>$('#reloadButton').click();$('#reloadMessagesButton').click();closeModal();</script>"
                        )
            except self.model.DoesNotExist:
                messages.error(request, _("The requested attachment does not exist."))
                return HttpResponse(
                    "<script>$('#reloadButton').click();$('#reloadMessagesButton').click();closeModal();</script>"
                )

        # For create mode, check permission on the related object
        else:
            model_name = request.GET.get("model_name")
            object_id = request.GET.get("object_id")

            if model_name and object_id:
                try:
                    content_type = HorillaContentType.objects.get(
                        model=model_name.lower()
                    )
                    related_model = content_type.model_class()
                    related_object = related_model.objects.get(pk=object_id)

                    if not self.check_related_object_permission(related_object, "add"):
                        messages.error(
                            request,
                            _(
                                "You don't have permission to add attachments to this record."
                            ),
                        )
                        return HttpResponse(
                            "<script>$('#reloadButton').click();$('#reloadMessagesButton').click();closeModal();</script>"
                        )
                except (
                    HorillaContentType.DoesNotExist,
                    related_model.DoesNotExist,
                    ValueError,
                ):
                    messages.error(request, _("Invalid related object."))
                    return HttpResponse(
                        "<script>$('#reloadButton').click();$('#reloadMessagesButton').click();closeModal();</script>"
                    )

        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        """Save attachment (create or update) and return close-modal/reload script."""
        model_name = self.request.GET.get("model_name")
        pk = self.kwargs.get("pk")

        attachment = form.save(commit=False)
        if not pk:
            content_type = HorillaContentType.objects.get(model=model_name.lower())
            attachment.created_by = self.request.user
            attachment.object_id = self.request.GET.get("object_id")
            attachment.content_type = content_type
            attachment.company = self.request.active_company
            messages.success(self.request, f"{attachment.title} created successfully")
        else:
            messages.success(self.request, f"{attachment.title} updated successfully")
        attachment.save()
        return HttpResponse(
            "<script>$('#tab-notes-attachments').click();closeModal();$('#detailReloadButton').click();</script>"
        )

    def get(self, request, *args, **kwargs):
        """Validate attachment pk when editing; then delegate to parent get."""
        pk = kwargs.get("pk")
        if pk:
            try:
                self.model.objects.get(pk=pk)
            except self.model.DoesNotExist:
                messages.error(request, "The requested attachment does not exist.")
                return HttpResponse(
                    "<script>$('#reloadButton').click();$('#reloadMessagesButton').click();closeModal();</script>"
                )

        return super().get(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.delete_horillaattachment", modal=True),
    name="dispatch",
)
class HorillaNotesAttachmentDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View for deleting notes and attachments."""

    model = HorillaAttachment

    def get_post_delete_response(self):
        return HttpResponse(
            "<script>htmx.trigger('#reloadButton','click');closeContentModal();</script>"
        )
