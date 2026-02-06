"""
Views for Horilla Mail app
"""

import base64
import html
import logging
import re
from datetime import datetime

from django.apps import apps
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import TemplateView

from horilla_core.decorators import htmx_required, permission_required_or_denied
from horilla_generics.views import HorillaSingleDeleteView
from horilla_mail.models import (
    HorillaMail,
    HorillaMailAttachment,
    HorillaMailConfiguration,
)
from horilla_mail.services import HorillaMailManager
from horilla_utils.middlewares import _thread_local

logger = logging.getLogger(__name__)


def parse_email_pills_context(email_string, field_type):
    """
    Helper function to parse email strings into pills context
    """
    email_list = []
    if email_string:
        email_list = [e.strip() for e in email_string.split(",") if e.strip()]

    return {
        "email_list": email_list,
        "email_string": email_string or "",
        "field_type": field_type,
        "current_search": "",
    }


def extract_inline_images_with_cid(html_content):
    """Extract base64 inline images and replace with CID references."""
    if not html_content:
        return html_content, []

    inline_images = []
    img_pattern = (
        r'<img([^>]*)src=["\']data:image/([^;]+);base64,([^"\']+)["\']([^>]*)>'
    )

    def replace_img(match):
        before_src = match.group(1)
        image_format = match.group(2)
        base64_data = match.group(3)
        after_src = match.group(4)

        try:
            image_data = base64.b64decode(base64_data)
            cid = f"inline_image_{len(inline_images) + 1}"
            filename = f"{cid}.{image_format}"
            content_file = ContentFile(image_data, name=filename)
            inline_images.append((content_file, cid))
            return f'<img{before_src}src="cid:{cid}"{after_src}>'
        except Exception as e:
            logger.error("Error processing inline image: %s", e)
            return match.group(0)

    cleaned_html = re.sub(img_pattern, replace_img, html_content, flags=re.IGNORECASE)
    return cleaned_html, inline_images


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "horilla_mail.view_horillamailconfiguration",
            "horilla_mail.add_horillamailconfiguration",
        ]
    ),
    name="dispatch",
)
class HorillaMailFormView(LoginRequiredMixin, TemplateView):
    """
    Send mail form view - automatically creates a draft mail
    """

    template_name = "mail_form.html"

    def get(self, request, *args, **kwargs):
        company = request.active_company
        outgoing_mail_exists = HorillaMailConfiguration.objects.filter(
            mail_channel="outgoing", company=company, is_active=True
        ).exists()

        if not outgoing_mail_exists:
            return render(
                request,
                "mail_config_required.html",
                {
                    "message": _(
                        "Cannot send email. Outgoing mail must be configured first."
                    ),
                },
            )
        pk = kwargs.get("pk") or request.GET.get("pk")
        cancel = self.request.GET.get("cancel") == "true"
        if pk:
            try:
                draft_mail = HorillaMail.objects.get(pk=pk)
                if cancel:
                    draft_mail.mail_status = "draft"
                    draft_mail.save()
            except Exception as e:
                messages.error(self.request, e)
                return HttpResponse(
                    "<script>$('reloadButton').click();closeModal();</script>"
                )

        return super().get(request, *args, **kwargs)

    def _extract_form_data(self, request):
        """Extract form data from request."""
        pk_value = request.GET.get("pk") or request.POST.get("pk")
        # Normalize pk: convert string 'None', 'null', or empty to None
        if pk_value in (None, "", "None", "null"):
            pk_value = None

        # Try to get model_name and object_id from both GET and POST
        model_name = request.GET.get("model_name") or request.POST.get("model_name")
        object_id = request.GET.get("object_id") or request.POST.get("object_id")

        return {
            "to_email": request.POST.get("to_email", ""),
            "cc_email": request.POST.get("cc_email", ""),
            "bcc_email": request.POST.get("bcc_email", ""),
            "subject": request.POST.get("subject", ""),
            "message_content": request.POST.get("message_content", ""),
            "from_mail_id": request.POST.get("from_mail"),
            "uploaded_files": request.FILES.getlist("attachments"),
            "model_name": model_name,
            "object_id": object_id,
            "pk": pk_value,
            "company": getattr(request, "active_company", None),
        }

    def _validate_required_fields(self, form_data):
        """Validate required fields and return validation errors dict."""
        validation_errors = {}
        if not form_data["to_email"]:
            validation_errors["to_email"] = _("To email is required")
        if not form_data["from_mail_id"]:
            validation_errors["from_mail"] = _("From mail configuration is required")
        return validation_errors

    def _build_validation_error_response(self, form_data, validation_errors, kwargs):
        """Build and return validation error response."""
        context = self.get_context_data(**kwargs)
        context["validation_errors"] = validation_errors
        context["subject"] = form_data["subject"]
        context["message_content"] = form_data["message_content"]
        context["form_data"] = {
            "to_email": form_data["to_email"],
            "cc_email": form_data["cc_email"],
            "bcc_email": form_data["bcc_email"],
            "subject": form_data["subject"],
            "message_content": form_data["message_content"],
            "from_mail_id": form_data["from_mail_id"],
        }
        context["to_pills"] = parse_email_pills_context(
            form_data["to_email"] or "", "to"
        )
        context["cc_pills"] = parse_email_pills_context(
            form_data["cc_email"] or "", "cc"
        )
        context["bcc_pills"] = parse_email_pills_context(
            form_data["bcc_email"] or "", "bcc"
        )
        response = self.render_to_response(context)
        response["HX-Select"] = "#send-mail-container"
        return response

    def _get_content_type(self, model_name, object_id, request):
        """Get ContentType for model_name if provided."""
        if not (model_name and object_id):
            return None
        try:
            return ContentType.objects.get(model=model_name.lower())
        except ContentType.DoesNotExist:
            messages.error(request, f"Invalid model name: {model_name}")
            return None

    def _get_or_create_draft_mail(
        self, form_data, from_mail_config, content_type, request
    ):
        """Get existing draft mail or create a new one."""
        draft_mail = None
        if content_type and form_data["object_id"]:
            try:
                draft_mail = HorillaMail.objects.filter(
                    pk=form_data["pk"],
                    content_type=content_type,
                    object_id=form_data["object_id"],
                    mail_status="draft",
                    created_by=request.user,
                ).first()
            except Exception as e:
                logger.error("Error finding draft: %s", e)

        if not draft_mail:
            draft_mail = HorillaMail.objects.create(
                content_type=content_type,
                object_id=form_data["object_id"] or 0,
                mail_status="draft",
                created_by=request.user,
                sender=from_mail_config,
                company=form_data["company"],
            )
        return draft_mail

    def _update_draft_mail(self, draft_mail, form_data, from_mail_config):
        """Update draft mail with form data."""
        cleaned_message_content, inline_images = extract_inline_images_with_cid(
            form_data["message_content"]
        )
        draft_mail.sender = from_mail_config
        draft_mail.to = form_data["to_email"]
        draft_mail.cc = form_data["cc_email"] if form_data["cc_email"] else None
        draft_mail.bcc = form_data["bcc_email"] if form_data["bcc_email"] else None
        draft_mail.subject = form_data["subject"] if form_data["subject"] else None
        draft_mail.body = cleaned_message_content if cleaned_message_content else None
        draft_mail.save()
        return inline_images

    def _save_attachments(self, draft_mail, form_data, inline_images):
        """Save file attachments and inline images."""
        if not draft_mail.pk:
            return
        for uploaded_file in form_data["uploaded_files"]:
            attachment = HorillaMailAttachment(
                mail=draft_mail, file=uploaded_file, company=form_data["company"]
            )
            attachment.save()
        for img_file, cid in inline_images:
            attachment = HorillaMailAttachment(
                mail=draft_mail,
                file=img_file,
                company=form_data["company"],
                is_inline=True,
                content_id=cid,
            )
            attachment.save()

    def _build_template_context(self, request, content_type, object_id):
        """Build template context for email sending."""
        template_context = {
            "user": request.user,
            "request": request,
        }
        if hasattr(request, "active_company") and request.active_company:
            template_context["active_company"] = (request.active_company,)
        if content_type and object_id:
            try:
                model_class = apps.get_model(
                    app_label=content_type.app_label, model_name=content_type.model
                )
                related_object = model_class.objects.get(pk=object_id)
                template_context["instance"] = related_object
            except Exception as e:
                logger.error("Error getting related object: %s", e)
        return template_context

    def post(self, request, *args, **kwargs):
        """
        Handle the submission of the mail form.
        """
        try:
            form_data = self._extract_form_data(request)
            setattr(_thread_local, "from_mail_id", form_data["from_mail_id"])

            validation_errors = self._validate_required_fields(form_data)
            if validation_errors:
                return self._build_validation_error_response(
                    form_data, validation_errors, kwargs
                )

            # XSS validation is now handled at model level via clean() method

            try:
                from_mail_config = HorillaMailConfiguration.objects.get(
                    id=form_data["from_mail_id"]
                )
            except HorillaMailConfiguration.DoesNotExist:
                return JsonResponse(
                    {"success": False, "message": "Invalid mail configuration selected"}
                )

            # If we have a pk, get the draft_mail first to extract model_name and object_id
            draft_mail = None
            content_type = None
            pk_value = form_data.get("pk")
            # pk_value is already normalized in _extract_form_data, just check if it exists
            if pk_value:
                try:
                    # Ensure it's an integer
                    pk_value = int(pk_value)
                    draft_mail = HorillaMail.objects.get(
                        pk=pk_value,
                        mail_status="draft",
                        created_by=request.user,
                    )
                    # Use content_type from existing draft_mail
                    content_type = draft_mail.content_type
                    # Extract model_name and object_id from existing draft_mail
                    if draft_mail.content_type:
                        form_data["model_name"] = draft_mail.content_type.model
                    if draft_mail.object_id:
                        form_data["object_id"] = draft_mail.object_id
                except (HorillaMail.DoesNotExist, ValueError):
                    pass

            if not content_type:
                if form_data.get("model_name") and form_data.get("object_id"):
                    content_type = self._get_content_type(
                        form_data["model_name"], form_data["object_id"], request
                    )
                    if not content_type:
                        # Error already shown in _get_content_type, just return
                        return HttpResponse(
                            "<script>closehorillaModal();"
                            "htmx.trigger('#reloadButton','click');</script>"
                        )
                else:
                    if draft_mail and draft_mail.content_type:
                        content_type = draft_mail.content_type
                        form_data["model_name"] = draft_mail.content_type.model
                        form_data["object_id"] = draft_mail.object_id
                    elif not content_type and (
                        form_data.get("model_name") or form_data.get("object_id")
                    ):
                        messages.error(
                            request,
                            _(
                                "Both model_name and object_id are required to send mail related to an object."
                            ),
                        )
                        return HttpResponse(
                            "<script>closehorillaModal();"
                            "htmx.trigger('#reloadButton','click');</script>"
                        )

            # For sending mail, only use existing draft if pk exists, don't create new draft
            # Create a mail object for sending (will be saved only if successfully sent)
            if not draft_mail:
                if not content_type:
                    messages.error(
                        request,
                        _(
                            "Cannot send mail: model information is missing. Please try again from the opportunity page."
                        ),
                    )
                    return HttpResponse(
                        "<script>closehorillaModal();"
                        "htmx.trigger('#reloadButton','click');</script>"
                    )
                # Create mail object for sending (not saved yet, will be saved only if sent successfully)
                cleaned_message_content, inline_images = extract_inline_images_with_cid(
                    form_data["message_content"]
                )
                draft_mail = HorillaMail(
                    content_type=content_type,
                    object_id=form_data["object_id"] or 0,
                    mail_status="draft",  # Will be changed to "sent" if successful
                    created_by=request.user,
                    sender=from_mail_config,
                    company=form_data["company"],
                    to=form_data["to_email"],
                    cc=form_data["cc_email"] if form_data["cc_email"] else None,
                    bcc=form_data["bcc_email"] if form_data["bcc_email"] else None,
                    subject=form_data["subject"] if form_data["subject"] else None,
                    body=cleaned_message_content if cleaned_message_content else None,
                )
            else:
                # Update existing draft with form data
                inline_images = self._update_draft_mail(
                    draft_mail, form_data, from_mail_config
                )

            # Validate before sending (but don't save as draft yet)
            try:
                draft_mail.full_clean()
            except ValidationError as e:
                validation_errors = {}
                if hasattr(e, "error_dict"):
                    for field, errors in e.error_dict.items():
                        if errors:
                            validation_errors[field] = " ".join(
                                [str(err) for err in errors]
                            )
                        else:
                            validation_errors[field] = str(e)
                elif hasattr(e, "error_list"):
                    validation_errors["non_field_errors"] = " ".join(
                        [str(err) for err in e.error_list]
                    )
                else:
                    validation_errors["non_field_errors"] = str(e)

                return self._build_validation_error_response(
                    form_data, validation_errors, kwargs
                )

            # Save mail object (needed for attachments and sending)
            # If it's a new mail, save it first to get pk for attachments
            if not draft_mail.pk:
                draft_mail.save()

            self._save_attachments(draft_mail, form_data, inline_images)

            object_id = (
                draft_mail.object_id
                if draft_mail and draft_mail.object_id
                else form_data["object_id"]
            )
            template_context = self._build_template_context(
                request, content_type, object_id
            )

            # Send mail - this will update status to "sent" or "failed" and save
            HorillaMailManager.send_mail(draft_mail, template_context)
            draft_mail.refresh_from_db()

            if draft_mail.mail_status == "sent":
                messages.success(request, _("Mail sent successfully"))
                # Mail is now saved with status "sent", not "draft"
            else:
                # If sending failed, delete the draft that was created for sending
                if not form_data.get(
                    "pk"
                ):  # Only delete if it was a new mail (not existing draft)
                    try:
                        draft_mail.delete()
                    except Exception:
                        pass
                messages.error(
                    request, _("Failed to send mail: ") + draft_mail.mail_status_message
                )
            return HttpResponse(
                "<script>closehorillaModal();htmx.trigger('#sent-email-tab','click');</script>"
            )

        except Exception as e:
            import traceback

            logger.error(traceback.format_exc())

            messages.error(request, _("Error sending mail: ") + str(e))
            return HttpResponse(
                "<script>closehorillaModal();htmx.trigger('#reloadButton','click');</script>"
            )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        draft_mail = None

        model_name = self.request.GET.get("model_name")
        object_id = self.request.GET.get("object_id")
        pk = kwargs.get("pk")
        primary_mail_config = HorillaMailConfiguration.objects.filter(
            is_primary=True
        ).first()
        if not primary_mail_config:
            primary_mail_config = HorillaMailConfiguration.objects.first()
        all_mail_configs = HorillaMailConfiguration.objects.filter(
            mail_channel="outgoing"
        )

        if pk:
            draft_mail = HorillaMail.objects.filter(pk=pk).first()
            # If we have an existing draft_mail, try to get the related object
            if draft_mail and draft_mail.content_type and draft_mail.object_id:
                try:
                    model_class = apps.get_model(
                        app_label=draft_mail.content_type.app_label,
                        model_name=draft_mail.content_type.model,
                    )
                    related_object = model_class.objects.get(pk=draft_mail.object_id)
                    context["related_object"] = related_object
                except Exception as e:
                    logger.error("Error getting related object from draft_mail: %s", e)
                    context["related_object"] = None
            else:
                context["related_object"] = None

        else:
            if model_name and object_id:
                try:
                    content_type = ContentType.objects.get(model=model_name.lower())

                    company = getattr(self.request, "active_company", None)

                    try:
                        draft_mail = HorillaMail.objects.create(
                            content_type=content_type,
                            created_by=self.request.user,
                            object_id=object_id,
                            mail_status="draft",
                            sender=primary_mail_config,
                            company=company,
                        )
                        created = True

                        if created:
                            try:
                                model_class = apps.get_model(
                                    app_label=content_type.app_label,
                                    model_name=content_type.model,
                                )
                                related_object = model_class.objects.get(pk=object_id)

                                # Try to find an email field in the related object
                                email_value = None
                                for field in related_object._meta.get_fields():
                                    if (
                                        "email" in field.name.lower()
                                        or field.__class__.__name__ == "EmailField"
                                    ):
                                        email_value = getattr(
                                            related_object, field.name, None
                                        )
                                        if email_value:
                                            break

                                # If we found an email, set it in the draft
                                if email_value:
                                    draft_mail.to = email_value
                                    draft_mail.save()

                            except Exception as e:
                                logger.error(
                                    "Error setting related object email: %s", e
                                )

                    except Exception as e:
                        logger.error(str(e))

                    try:
                        model_class = apps.get_model(
                            app_label=content_type.app_label,
                            model_name=content_type.model,
                        )
                        related_object = model_class.objects.get(pk=object_id)
                        context["related_object"] = related_object
                    except Exception as e:
                        context["related_object"] = None

                except ContentType.DoesNotExist:
                    pass
                except Exception as e:
                    pass
        existing_attachments = draft_mail.attachments.all() if draft_mail else []
        context["existing_attachments"] = existing_attachments
        context["message_content"] = (
            draft_mail.body if draft_mail and draft_mail.body else ""
        )
        context["subject"] = (
            draft_mail.subject if draft_mail and draft_mail.subject else ""
        )

        # Get model_name: prefer from draft_mail.content_type, fallback to GET param
        context_model_name = None
        if draft_mail and draft_mail.content_type:
            context_model_name = draft_mail.content_type.model.capitalize()
        elif model_name:
            # Use the model_name from GET params if draft_mail doesn't have it
            context_model_name = model_name.capitalize()

        context["model_name"] = context_model_name
        context["object_id"] = (
            draft_mail.object_id if draft_mail and draft_mail.object_id else object_id
        )
        context["pk"] = draft_mail.pk if draft_mail else None
        context["draft_mail"] = draft_mail
        context["primary_mail_config"] = primary_mail_config
        context["all_mail_configs"] = all_mail_configs
        context["to_pills"] = parse_email_pills_context(
            draft_mail.to if draft_mail else "", "to"
        )
        context["cc_pills"] = parse_email_pills_context(
            draft_mail.cc if draft_mail else "", "cc"
        )
        context["bcc_pills"] = parse_email_pills_context(
            draft_mail.bcc if draft_mail else "", "bcc"
        )
        return context


@method_decorator(
    permission_required_or_denied(
        [
            "horilla_mail.change_horillamailconfiguration",
            "horilla_mail.add_horillamailconfiguration",
        ]
    ),
    name="dispatch",
)
class AddEmailView(LoginRequiredMixin, View):
    """
    View to add email as a pill and clear search input
    """

    def post(self, request, *args, **kwargs):
        """
        Add email to the pill list
        """
        email = request.POST.get("email", "").strip()
        field_type = request.POST.get("field_type", "to")
        current_email_list = request.POST.get(f"{field_type}_email_list", "")

        if current_email_list:
            email_list = [e.strip() for e in current_email_list.split(",") if e.strip()]
        else:
            email_list = []

        if email and email not in email_list:
            email_list.append(email)

        email_string = ", ".join(email_list)

        context = {
            "email_list": email_list,
            "email_string": email_string,
            "field_type": field_type,
            "current_search": "",
        }

        return render(request, "email_pills_field.html", context)


@method_decorator(
    permission_required_or_denied(
        [
            "horilla_mail.change_horillamailconfiguration",
            "horilla_mail.add_horillamailconfiguration",
        ]
    ),
    name="dispatch",
)
class RemoveEmailView(LoginRequiredMixin, View):
    """
    View to remove specific email pill
    """

    def post(self, request, *args, **kwargs):
        """
        Remove email from the pill list
        """
        email_to_remove = request.POST.get("email_to_remove", "").strip()
        field_type = request.POST.get("field_type", "to")
        current_email_list = request.POST.get(f"{field_type}_email_list", "")

        if current_email_list:
            email_list = [e.strip() for e in current_email_list.split(",") if e.strip()]
        else:
            email_list = []

        if email_to_remove in email_list:
            email_list.remove(email_to_remove)

        email_string = ", ".join(email_list)

        context = {
            "email_list": email_list,
            "email_string": email_string,
            "field_type": field_type,
            "current_search": "",
        }

        return render(request, "email_pills_field.html", context)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "horilla_mail.change_horillamailconfiguration",
            "horilla_mail.view_horillamailconfiguration",
        ]
    ),
    name="dispatch",
)
class EmailSuggestionView(LoginRequiredMixin, View):
    """
    View to get email suggestions (updated to work with pills)
    """

    def get_all_emails_from_models(self):
        """
        Extract all email addresses from all models in the project
        """
        all_emails = set()

        for model in apps.get_models():
            model_name = model._meta.model_name.lower()
            if model_name in [
                "session",
                "contenttype",
                "permission",
                "group",
                "logentry",
            ]:
                continue

            for field in model._meta.get_fields():
                if (
                    "email" in field.name.lower()
                    or field.__class__.__name__ == "EmailField"
                ):

                    try:
                        values = model.objects.values_list(
                            field.name, flat=True
                        ).distinct()
                        for value in values:
                            if value and "@" in str(value):
                                self._extract_emails_from_string(str(value), all_emails)
                    except Exception:
                        continue

        try:
            for field_name in ["to", "cc", "bcc"]:
                try:
                    email_values = HorillaMail.objects.values_list(
                        field_name, flat=True
                    ).distinct()
                    for email_string in email_values:
                        if email_string:
                            self._extract_emails_from_string(email_string, all_emails)
                except Exception:
                    continue

        except ImportError:
            pass

        valid_emails = []
        for email in all_emails:
            if self._is_valid_email(email):
                valid_emails.append(email.lower())

        return sorted(list(set(valid_emails)))

    def _extract_emails_from_string(self, email_string, email_set):
        """
        Extract individual emails from a string that might contain multiple emails
        """
        if "," in email_string:
            emails = [email.strip() for email in email_string.split(",")]
            email_set.update(emails)
        elif ";" in email_string:
            emails = [email.strip() for email in email_string.split(";")]
            email_set.update(emails)
        else:
            email_set.add(email_string.strip())

    def _is_valid_email(self, email):
        """
        Basic email validation
        """
        if not email or len(email) < 5:
            return False
        if "@" not in email:
            return False
        parts = email.split("@")
        if len(parts) != 2:
            return False
        if "." not in parts[1]:
            return False
        return True

    def get(self, request, *args, **kwargs):
        """
        Return email suggestions based on search query
        """
        field_type = request.GET.get("field", "to")
        current_input = request.GET.get(f"{field_type}_email_input", "").strip()
        current_email_list = request.GET.get(f"{field_type}_email_list", "")

        existing_emails = []
        if current_email_list:
            existing_emails = [
                e.strip().lower() for e in current_email_list.split(",") if e.strip()
            ]

        all_emails = self.get_all_emails_from_models()

        available_emails = [
            email for email in all_emails if email.lower() not in existing_emails
        ]

        if current_input:
            search_lower = current_input.lower()
            filtered_emails = [
                email for email in available_emails if search_lower in email.lower()
            ]
            exact_matches = [e for e in filtered_emails if e.lower() == search_lower]
            starts_with = [
                e
                for e in filtered_emails
                if e.lower().startswith(search_lower) and e not in exact_matches
            ]
            contains = [
                e
                for e in filtered_emails
                if search_lower in e.lower()
                and e not in exact_matches
                and e not in starts_with
            ]

            filtered_emails = exact_matches + starts_with + contains
        else:
            filtered_emails = available_emails[:10]

        filtered_emails = filtered_emails[:15]

        context = {
            "emails": filtered_emails,
            "field_type": field_type,
            "query": current_input,
        }

        return render(request, "email_suggestions.html", context)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "horilla_mail.change_horillamailconfiguration",
            "horilla_mail.view_horillamailconfiguration",
        ]
    ),
    name="dispatch",
)
class HorillaMailFieldSelectionView(LoginRequiredMixin, TemplateView):
    """
    View to show all fields of the related model for insertion into email templates
    """

    template_name = "field_selection_modal.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        model_name = self.request.GET.get("model_name")
        object_id = self.request.GET.get("object_id")
        content_type_id = self.request.GET.get("content_type")

        if model_name or content_type_id:
            tab_type = self.request.GET.get(
                "tab_type", "instance"
            )  # Default to instance if model exists
        else:
            tab_type = self.request.GET.get(
                "tab_type", "user"
            )  # Default to user if no model

        excluded_fields = {
            "is_active",
            "additional_info",
            "history",
            "password",
            "user_permissions",
            "groups",
            "last_login",
            "date_joined",
            "is_staff",
            "is_superuser",
            "recycle_bin_policy",
        }

        try:
            if tab_type == "instance" and model_name or content_type_id:
                if model_name:
                    content_type = ContentType.objects.get(model=model_name.lower())
                else:
                    content_type = ContentType.objects.get(id=content_type_id)
                    model_name = content_type.model_class()._meta.verbose_name
                model_class = apps.get_model(
                    app_label=content_type.app_label, model_name=content_type.model
                )
                related_object = None
                if object_id and object_id != "None":
                    related_object = model_class.objects.get(pk=object_id)

                model_fields = []

                # Get regular fields
                for field in model_class._meta.get_fields():
                    if field.name in excluded_fields:
                        continue

                    if not field.many_to_many and not field.one_to_many:
                        field_info = {
                            "name": field.name,
                            "verbose_name": getattr(field, "verbose_name", field.name),
                            "field_type": field.__class__.__name__,
                            "template_syntax": f"{{{{ instance.{field.name} }}}}",
                            "is_foreign_key": (
                                field.many_to_one
                                if hasattr(field, "many_to_one")
                                else False
                            ),
                            "is_relation": hasattr(field, "related_model"),
                        }

                        model_fields.append(field_info)

                foreign_key_fields = []
                for field in model_class._meta.get_fields():
                    # Skip excluded fields
                    if field.name in excluded_fields:
                        continue

                    if field.many_to_one and hasattr(field, "related_model"):
                        # Get fields from the related model without needing object instance
                        for related_field in field.related_model._meta.get_fields():
                            # Skip excluded fields in related model too
                            if related_field.name in excluded_fields:
                                continue

                            if (
                                not related_field.many_to_many
                                and not related_field.one_to_many
                            ):
                                fk_field_info = {
                                    "name": (f"{field.name}.{related_field.name}"),
                                    "verbose_name": (
                                        getattr(
                                            related_field,
                                            "verbose_name",
                                            related_field.name,
                                        )
                                    ),
                                    "header": field.verbose_name,
                                    "field_type": (
                                        f"{field.__class__.__name__} -> "
                                        f"{related_field.__class__.__name__}"
                                    ),
                                    "template_syntax": (
                                        f"{{{{ instance.{field.name}."
                                        f"{related_field.name} }}}}"
                                    ),
                                    "parent_field": field.name,
                                    "is_foreign_key": True,
                                }

                                foreign_key_fields.append(fk_field_info)

                reverse_relation_fields = []

                # Get all reverse relations
                for field in model_class._meta.get_fields():
                    if field.one_to_many or field.many_to_many:
                        # Skip fields that don't have get_accessor_name method
                        # (e.g., AuditlogHistoryField)
                        if not hasattr(field, "get_accessor_name"):
                            continue
                        try:
                            # Get the accessor name (like 'employee_set' or custom related_name)
                            accessor_name = field.get_accessor_name()

                            related_model = field.related_model

                            if related_model:
                                for reverse_field in related_model._meta.get_fields():
                                    if (
                                        reverse_field.name in excluded_fields
                                        or reverse_field.many_to_many
                                        or reverse_field.one_to_many
                                    ):
                                        continue

                                    if (
                                        hasattr(reverse_field, "related_model")
                                        and reverse_field.related_model == model_class
                                    ):
                                        continue

                                    reverse_field_info = {
                                        "name": (
                                            f"{accessor_name}.first."
                                            f"{reverse_field.name}"
                                        ),
                                        "verbose_name": (
                                            getattr(
                                                reverse_field,
                                                "verbose_name",
                                                reverse_field.name,
                                            )
                                        ),
                                        "header": field.related_model._meta.verbose_name,
                                        "field_type": (
                                            f"Reverse {field.__class__.__name__} -> "
                                            f"{reverse_field.__class__.__name__}"
                                        ),
                                        "template_syntax": (
                                            f"{{{{ instance.{accessor_name}."
                                            f"first.{reverse_field.name} }}}}"
                                        ),
                                        "parent_field": accessor_name,
                                        "is_reverse_relation": True,
                                    }

                                    reverse_relation_fields.append(reverse_field_info)
                        except Exception as e:
                            logger.error(
                                "Error processing reverse relation splits: %s",
                                e,
                            )
                            continue

                context["model_fields"] = model_fields
                context["foreign_key_fields"] = foreign_key_fields
                context["reverse_relation_fields"] = reverse_relation_fields
                context["related_object"] = related_object

            elif tab_type == "user":
                user = self.request.user
                model_fields = []

                for field in user._meta.get_fields():
                    if field.name in excluded_fields:
                        continue

                    if not field.many_to_many and not field.one_to_many:
                        field_info = {
                            "name": field.name,
                            "verbose_name": getattr(field, "verbose_name", field.name),
                            "field_type": field.__class__.__name__,
                            "template_syntax": f"{{{{ request.user.{field.name} }}}}",
                            "is_foreign_key": (
                                field.many_to_one
                                if hasattr(field, "many_to_one")
                                else False
                            ),
                            "is_relation": hasattr(field, "related_model"),
                        }

                        model_fields.append(field_info)

                context["model_fields"] = model_fields
                context["foreign_key_fields"] = []
                context["reverse_relation_fields"] = []
                context["related_object"] = user

            elif tab_type == "company":
                # Get current active company fields
                company = getattr(self.request, "active_company", None)

                if company:
                    model_fields = []

                    for field in company._meta.get_fields():
                        if field.name in excluded_fields:
                            continue

                        if not field.many_to_many and not field.one_to_many:
                            field_info = {
                                "name": field.name,
                                "verbose_name": getattr(
                                    field, "verbose_name", field.name
                                ),
                                "field_type": field.__class__.__name__,
                                "template_syntax": f"{{{{ request.active_company.{field.name} }}}}",
                                "is_foreign_key": (
                                    field.many_to_one
                                    if hasattr(field, "many_to_one")
                                    else False
                                ),
                                "is_relation": hasattr(field, "related_model"),
                            }

                            model_fields.append(field_info)

                    context["model_fields"] = model_fields
                    context["foreign_key_fields"] = []
                    context["reverse_relation_fields"] = []
                    context["related_object"] = company
                else:
                    context["error"] = "No active company found"

            elif tab_type == "request":
                # Get request object fields (commonly used request attributes)
                request_fields = [
                    {
                        "name": "get_host",
                        "verbose_name": "Host",
                        "template_syntax": "{{ request.get_host }}",
                    },
                    {
                        "name": "scheme",
                        "verbose_name": "Scheme",
                        "template_syntax": "{{ request.scheme }}",
                    },
                ]

                model_fields = []
                for field_data in request_fields:
                    field_info = {
                        "name": field_data["name"],
                        "verbose_name": field_data["verbose_name"],
                        "field_type": "RequestAttribute",
                        "template_syntax": field_data["template_syntax"],
                        "is_foreign_key": False,
                        "is_relation": False,
                    }

                    model_fields.append(field_info)

                context["model_fields"] = model_fields
                context["foreign_key_fields"] = []
                context["reverse_relation_fields"] = []
                context["related_object"] = self.request

            context["has_model_name"] = bool(model_name) or bool(content_type_id)
            context["model_name"] = model_name
            context["object_id"] = object_id
            context["tab_type"] = tab_type

        except Exception as e:
            context["error"] = f"Error loading fields: {str(e)}"
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "horilla_mail.change_horillamailconfiguration",
            "horilla_mail.view_horillamailconfiguration",
        ]
    ),
    name="dispatch",
)
class HorillaMailPreviewView(LoginRequiredMixin, View):
    """
    Preview mail content using existing draft mail object and its render methods
    """

    def get(self, request, *args, **kwargs):
        """
        Render preview of the mail
        """

        pk = self.kwargs.get("pk")
        draft_mail = HorillaMail.objects.filter(pk=pk).first()
        try:
            from_mail_config = HorillaMailConfiguration.objects.get(
                id=draft_mail.sender.id
            )
        except Exception as e:
            messages.error(self.request, e)
            return HttpResponse(
                "<script>$('reloadButton').click();closeContentModal();</script>"
            )

        attachments = []
        inline_attachments = {}

        existing_attachments = HorillaMailAttachment.objects.filter(
            mail=draft_mail.pk,
        )
        for attachment in existing_attachments:
            if attachment.is_inline:
                # Store inline attachments by their content_id for replacement
                if attachment.content_id:
                    inline_attachments[attachment.content_id] = attachment
                # Also store by filename as fallback
                inline_attachments[attachment.file_name()] = attachment
            else:
                attachments.append(attachment)

        # Render subject and body
        rendered_subject = draft_mail.render_subject()
        rendered_body = draft_mail.render_body()

        # Pattern to find cid: in src attributes and capture data-filename if present
        cid_pattern = re.compile(
            r'<img\s+([^>]*?)src=["\']cid:([^"\']+)["\']([^>]*?)>', re.IGNORECASE
        )

        def replace_cid(match):
            before_src = match.group(1)
            content_id = match.group(2)
            after_src = match.group(3)

            # Try to find by content_id first
            if content_id in inline_attachments:
                attachment = inline_attachments[content_id]
                return f'<img {before_src}src="{attachment.file.url}"{after_src}>'

            # Try to find by filename from data-filename attribute
            filename_match = re.search(
                r'data-filename=["\']([^"\']+)["\']', before_src + after_src
            )
            if filename_match:
                filename = filename_match.group(1)
                if filename in inline_attachments:
                    attachment = inline_attachments[filename]
                    return f'<img {before_src}src="{attachment.file.url}"{after_src}>'

            return match.group(0)  # Return original if not found

        rendered_body = cid_pattern.sub(replace_cid, rendered_body)
        rendered_body = mark_safe(rendered_body)

        preview_context = {
            "draft_mail": draft_mail,
            "to_email": draft_mail.to,
            "cc_email": draft_mail.cc,
            "bcc_email": draft_mail.bcc,
            "subject": rendered_subject,
            "message_content": rendered_body,
            "from_mail_config": from_mail_config,
            "attachments": attachments,
            "draft": False,
        }

        html_content = render_to_string(
            "mail_preview_modal.html", preview_context, request
        )
        return HttpResponse(html_content)

    def post(self, request, *args, **kwargs):
        """
        Generate preview based on form data without saving
        """
        try:
            # Get form data
            to_email = request.POST.get("to_email", "")
            cc_email = request.POST.get("cc_email", "")
            bcc_email = request.POST.get("bcc_email", "")
            subject = request.POST.get("subject", "")
            message_content = request.POST.get("message_content", "")
            from_mail_id = request.POST.get("from_mail")
            uploaded_files = request.FILES.getlist("attachments")

            model_name = request.GET.get("model_name")
            pk = request.GET.get("pk")
            object_id = request.GET.get("object_id")

            from_mail_config = None
            if from_mail_id:
                try:
                    from_mail_config = HorillaMailConfiguration.objects.get(
                        id=from_mail_id
                    )
                except HorillaMailConfiguration.DoesNotExist:
                    pass

            draft_mail = None
            content_type = None

            if model_name and object_id:
                try:
                    content_type = ContentType.objects.get(model=model_name.lower())
                    draft_mail = HorillaMail.objects.filter(pk=pk).first()
                except Exception as e:
                    logger.error("Error finding draft mail: %s", e)

            if not draft_mail:
                company = getattr(request, "active_company", None)
                draft_mail = HorillaMail(
                    content_type=content_type,
                    object_id=object_id or 0,
                    mail_status="draft",
                    created_by=request.user,
                    sender=from_mail_config,
                    company=company,
                )

            draft_mail.sender = from_mail_config
            draft_mail.to = to_email
            draft_mail.cc = cc_email if cc_email else None
            draft_mail.bcc = bcc_email if bcc_email else None
            draft_mail.subject = subject
            draft_mail.body = message_content

            template_context = {
                "request": request,
                "user": request.user,
            }

            if hasattr(request, "active_company") and request.active_company:
                template_context["active_company"] = (
                    request.active_company
                    if request.active_company
                    else request.user.company
                )

            if content_type and object_id:
                try:
                    model_class = apps.get_model(
                        app_label=content_type.app_label, model_name=content_type.model
                    )
                    related_object = model_class.objects.get(pk=object_id)
                    template_context["instance"] = related_object
                    draft_mail.related_to = related_object
                except Exception as e:
                    logger.error("Error getting related object: %s", e)

            rendered_subject = ""
            rendered_content = ""

            try:
                rendered_subject = draft_mail.render_subject(template_context)
            except Exception as e:
                rendered_subject = f"[Template Error in Subject: {str(e)}] {subject}"

            try:
                rendered_content = draft_mail.render_body(template_context)
            except Exception as e:
                rendered_content = (
                    f"<div class='alert alert-danger'>[Template Error: {str(e)}]</div>"
                    f"{message_content}"
                )

            attachments = []
            if draft_mail.pk:
                existing_attachments = HorillaMailAttachment.objects.filter(
                    mail=draft_mail.pk,
                )
                for attachment in existing_attachments:
                    attachments.append(attachment)
                for f in uploaded_files:

                    attachment = HorillaMailAttachment(
                        mail=draft_mail, file=f  # each file individually
                    )
                    attachment.save()
                    attachments.append(attachment)

            preview_context = {
                "draft_mail": draft_mail,
                "to_email": to_email,
                "cc_email": cc_email,
                "bcc_email": bcc_email,
                "subject": rendered_subject,
                "message_content": rendered_content,
                "from_mail_config": from_mail_config,
                "template_context": template_context,
                "attachments": attachments,
            }

            # Render preview template
            html_content = render_to_string(
                "mail_preview_modal.html", preview_context, request
            )
            return HttpResponse(html_content)

        except Exception as e:
            error_html = f"""
            <div class="p-5">
                <div class="flex justify-between items-center mb-4">
                    <h2 class="text-lg font-semibold text-red-600">Preview Error</h2>
                    <button onclick="closeContentModal()" class="text-gray-500 hover:text-red-500">
                        <img src="assets/icons/close.svg" alt="Close" />
                    </button>
                </div>
                <div class="bg-red-50 border border-red-200 rounded-md p-4">
                    <p class="text-red-800">Error generating preview: {html.escape(str(e))}</p>
                </div>
            </div>
            """
            return HttpResponse(error_html)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "horilla_mail.change_horillamailconfiguration",
            "horilla_mail.view_horillamailconfiguration",
        ]
    ),
    name="dispatch",
)
class CheckDraftChangesView(LoginRequiredMixin, View):
    """
    Check if there are changes to save and return appropriate modal content
    """

    def post(self, request, *args, **kwargs):
        """
        Always show confirmation modal when closing - user can choose to save or discard
        """
        model_name = request.GET.get("model_name")
        pk = request.GET.get("pk")
        object_id = request.GET.get("object_id")

        # Always show confirmation modal when closing
        return render(
            request,
            "draft_save_modal.html",
            {"model_name": model_name, "object_id": object_id, "pk": pk},
        )


@method_decorator(
    permission_required_or_denied(
        [
            "horilla_mail.change_horillamailconfiguration",
            "horilla_mail.view_horillamailconfiguration",
        ]
    ),
    name="dispatch",
)
class SaveDraftView(LoginRequiredMixin, View):
    """
    Save the current mail as draft
    """

    def post(self, request, *args, **kwargs):
        """
        Save draft mail
        """
        try:
            to_email = request.POST.get("to_email", "").strip()
            cc_email = request.POST.get("cc_email", "").strip()
            bcc_email = request.POST.get("bcc_email", "").strip()
            subject = request.POST.get("subject", "").strip()
            message_content = request.POST.get("message_content", "").strip()
            from_mail_id = request.POST.get("from_mail")
            uploaded_files = request.FILES.getlist("attachments")
            model_name = request.GET.get("model_name")
            object_id = request.GET.get("object_id")
            company = getattr(request, "active_company", None)
            pk = request.GET.get("pk")

            # Normalize empty HTML content (like <p><br></p> or <p></p>)
            def normalize_html_content(content):
                if not content:
                    return ""
                # Remove common empty HTML patterns
                normalized = content.strip()
                normalized = re.sub(
                    r"<p>\s*<br\s*/?>\s*</p>", "", normalized, flags=re.IGNORECASE
                )
                normalized = re.sub(r"<p>\s*</p>", "", normalized, flags=re.IGNORECASE)
                normalized = normalized.strip()
                return normalized

            normalized_message = normalize_html_content(message_content)

            # Get existing draft if pk exists
            draft_mail = None
            if pk:
                try:
                    draft_mail = HorillaMail.objects.get(
                        pk=pk,
                        mail_status="draft",
                        created_by=request.user,
                    )
                except HorillaMail.DoesNotExist:
                    pass

            # Check if there are actual changes
            has_changes = False

            if draft_mail:
                # Compare with existing draft
                draft_body = normalize_html_content(draft_mail.body or "")
                draft_to = (draft_mail.to or "").strip()
                draft_cc = (draft_mail.cc or "").strip()
                draft_bcc = (draft_mail.bcc or "").strip()
                draft_subject = (draft_mail.subject or "").strip()
                draft_from_id = (
                    str(draft_mail.sender_id) if draft_mail.sender_id else ""
                )

                if (
                    to_email != draft_to
                    or cc_email != draft_cc
                    or bcc_email != draft_bcc
                    or subject != draft_subject
                    or normalized_message != draft_body
                    or (from_mail_id and from_mail_id != draft_from_id)
                ):
                    has_changes = True
            else:
                # New draft - check if there's any actual content (not just empty HTML)
                has_changes = any(
                    [to_email, cc_email, bcc_email, subject, normalized_message]
                )

            # Check for new attachments
            if request.FILES.getlist("attachments"):
                has_changes = True

            # Only save if there are actual changes
            if not has_changes:
                messages.success(request, _("Draft saved successfully"))
                return HttpResponse(
                    "<script>closehorillaModal();"
                    "$('#draft-email-tab').click();"
                    "closeDeleteModeModal();</script>"
                )

            # Get or create mail configuration
            from_mail_config = None
            if from_mail_id:
                try:
                    from_mail_config = HorillaMailConfiguration.objects.get(
                        id=from_mail_id
                    )
                except HorillaMailConfiguration.DoesNotExist:
                    from_mail_config = HorillaMailConfiguration.objects.filter(
                        is_primary=True
                    ).first()

            if not from_mail_config:
                from_mail_config = HorillaMailConfiguration.objects.first()

            # Get content type
            content_type = None
            if model_name and object_id:
                try:
                    content_type = ContentType.objects.get(model=model_name.lower())
                except ContentType.DoesNotExist:
                    pass

            # Find or create draft (if we don't already have it from change detection)
            if not draft_mail:
                if content_type and object_id:
                    draft_mail = HorillaMail.objects.filter(
                        pk=pk,
                        content_type=content_type,
                        object_id=object_id,
                        mail_status="draft",
                        created_by=request.user,
                    ).first()

            if not draft_mail:

                draft_mail = HorillaMail.objects.create(
                    content_type=content_type,
                    object_id=object_id,
                    mail_status="draft",
                    created_by=request.user,
                    sender=from_mail_config,
                    company=company,
                )

            # Update draft with current data
            if from_mail_config:
                draft_mail.sender = from_mail_config
            draft_mail.to = to_email
            draft_mail.cc = cc_email if cc_email else None
            draft_mail.bcc = bcc_email if bcc_email else None
            draft_mail.subject = subject
            draft_mail.body = message_content
            draft_mail.save()
            if draft_mail.pk:
                for f in uploaded_files:
                    attachment = HorillaMailAttachment(
                        mail=draft_mail, file=f, company=company
                    )
                    attachment.save()
            messages.success(request, _("Draft saved successfully"))
            return HttpResponse(
                "<script>closehorillaModal();"
                "$('#draft-email-tab').click();"
                "closeDeleteModeModal();</script>"
            )

        except Exception as e:
            messages.error(request, _("Error saving draft: ") + str(e))
            return HttpResponse(
                "<script>closehorillaModal();"
                "htmx.trigger('#draft-email-tab','click');"
                "closeDeleteModeModal();</script>"
            )


@method_decorator(
    permission_required_or_denied(
        [
            "horilla_mail.change_horillamailconfiguration",
            "horilla_mail.view_horillamailconfiguration",
        ]
    ),
    name="dispatch",
)
class DiscardDraftView(LoginRequiredMixin, View):
    """
    Discard the draft without saving
    """

    def delete(self, request, *args, **kwargs):
        """
        Discard draft mail
        """
        try:
            model_name = request.GET.get("model_name")
            object_id = request.GET.get("object_id")
            pk = pk = request.GET.get("pk")

            if model_name and object_id:
                try:
                    content_type = ContentType.objects.get(model=model_name.lower())
                    HorillaMail.objects.filter(
                        pk=pk,
                        content_type=content_type,
                        object_id=object_id,
                        mail_status="draft",
                        created_by=request.user,
                    ).delete()
                except ContentType.DoesNotExist:
                    pass

            messages.info(request, _("Draft discarded"))
            return HttpResponse(
                "<script>closehorillaModal();"
                "$('#draft-email-tab').click();"
                "closeDeleteModeModal();</script>"
            )

        except Exception as e:
            messages.error(request, _("Error discarding draft: ") + str(e))
            return HttpResponse(
                "<script>closehorillaModal();"
                "htmx.trigger('#sent-email-tab','click');"
                "closeDeleteModeModal();</script>"
            )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        "horilla_mail.delete_horillamailconfiguration", modal=True
    ),
    name="dispatch",
)
class HorillaMailtDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete Horilla Mail view with post-delete redirection based on 'view' parameter
    """

    model = HorillaMail

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.view_param = None

    def post(self, request, *args, **kwargs):
        view_from_get = request.GET.get("view")
        if view_from_get:
            pk = kwargs.get("pk") or self.kwargs.get("pk")
            request.session[f"mail_delete_view_{pk}"] = view_from_get
            self.view_param = view_from_get
        else:
            pk = kwargs.get("pk") or self.kwargs.get("pk")
            self.view_param = request.session.get(f"mail_delete_view_{pk}")
        return super().post(request, *args, **kwargs)

    def get_post_delete_response(self):
        view = getattr(self, "view_param", None)

        if view:
            pk = self.kwargs.get("pk")
            session_key = f"mail_delete_view_{pk}"
            if session_key in self.request.session:
                del self.request.session[session_key]

        tab_map = {
            "sent": "sent-email-tab",
            "draft": "draft-email-tab",
            "scheduled": "scheduled-email-tab",
        }

        tab_id = tab_map.get(view)

        if tab_id:
            return HttpResponse(f"<script>$('#{tab_id}').click();</script>")

        return HttpResponse("<script>location.reload();</script>")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "horilla_mail.view_horillamailconfiguration",
            "horilla_mail.add_horillamailconfiguration",
        ]
    ),
    name="dispatch",
)
class ScheduleMailView(LoginRequiredMixin, View):
    """
    Schedule mail view - saves draft with scheduled send time
    """

    def _validate_schedule_datetime(self, scheduled_at):
        """Validate and parse scheduled datetime string."""
        if not scheduled_at:
            return None, {"schedule_datetime": _("Schedule time is required")}

        try:
            try:
                schedule_at_naive = datetime.strptime(scheduled_at, "%Y-%m-%dT%H:%M")
            except ValueError:
                schedule_at_naive = datetime.strptime(scheduled_at, "%Y-%m-%d %H:%M")

            user_tz = timezone.get_current_timezone()
            schedule_at = timezone.make_aware(schedule_at_naive, user_tz)

            if schedule_at <= timezone.now():
                return None, {
                    "schedule_datetime": _("Scheduled time must be in the future")
                }

            return schedule_at, {}
        except ValueError:
            return None, {"schedule_datetime": _("Invalid date/time format")}

    def _render_error_response(
        self,
        request,
        errors,
        model_name=None,
        object_id=None,
        pk=None,
        is_reschedule=False,
        scheduled_at="",
    ):
        """Render error response with form context."""
        non_field_errors = {k: v for k, v in errors.items() if k != "schedule_datetime"}
        context = {
            "model_name": model_name,
            "object_id": object_id,
            "pk": pk,
            "is_reschedule": is_reschedule,
            "errors": errors,
            "non_field_errors": non_field_errors,
            "scheduled_at": scheduled_at or "",
        }
        render_html = render_to_string(
            "schedule_mail_form.html", context, request=request
        )
        return HttpResponse(render_html)

    def _handle_reschedule(self, request, pk, scheduled_at):
        """Handle rescheduling of an existing mail."""
        errors = {}

        if not scheduled_at:
            errors["schedule_datetime"] = _("Schedule time is required")
            return self._render_error_response(
                request, errors, pk=pk, is_reschedule=True, scheduled_at=scheduled_at
            )

        try:
            draft_mail = HorillaMail.objects.get(pk=pk)
        except HorillaMail.DoesNotExist:
            errors["non_field_error"] = _(
                "Scheduled mail not found or you don't have permission"
            )
            return self._render_error_response(
                request, errors, pk=pk, is_reschedule=True, scheduled_at=scheduled_at
            )

        schedule_at, validation_errors = self._validate_schedule_datetime(scheduled_at)
        if validation_errors:
            return self._render_error_response(
                request,
                validation_errors,
                pk=pk,
                is_reschedule=True,
                scheduled_at=scheduled_at,
            )

        draft_mail.scheduled_at = schedule_at
        draft_mail.save(update_fields=["scheduled_at"])

        messages.success(
            request,
            _("Mail rescheduled successfully for ")
            + schedule_at.strftime("%Y-%m-%d %H:%M"),
        )
        return HttpResponse(
            "<script>closeModal();$('#scheduled-email-tab').click();</script>"
        )

    def _validate_form_fields(
        self, to_email, from_mail_id, scheduled_at, message_content
    ):
        """Validate form fields and return errors dict."""
        errors = {}

        if not to_email:
            errors["to_email"] = _("To email is required")
        if not from_mail_id:
            errors["from_mail"] = _("From mail configuration is required")
        if not scheduled_at:
            errors["schedule_datetime"] = _("Schedule time is required")

        # XSS validation is handled at model level via clean() method

        if scheduled_at:
            _schedule_at, validation_errors = self._validate_schedule_datetime(
                scheduled_at
            )
            errors.update(validation_errors)

        return errors

    def _get_or_create_draft_mail(
        self, request, pk, content_type, object_id, from_mail_config, company
    ):
        """Get existing draft mail or create a new one."""
        draft_mail = None
        if pk:
            try:
                draft_mail = HorillaMail.objects.get(
                    pk=pk,
                    mail_status="draft",
                    created_by=request.user,
                )
            except HorillaMail.DoesNotExist:
                pass

        if not draft_mail:
            draft_mail = HorillaMail.objects.create(
                content_type=content_type,
                object_id=object_id or 0,
                mail_status="scheduled",
                created_by=request.user,
                sender=from_mail_config,
                company=company,
            )

        return draft_mail

    def _save_mail_attachments(
        self, draft_mail, uploaded_files, inline_images, company
    ):
        """Save mail attachments and inline images."""
        if not draft_mail.pk:
            return

        for f in uploaded_files:
            attachment = HorillaMailAttachment(mail=draft_mail, file=f, company=company)
            attachment.save()

        for img_file, cid in inline_images:
            attachment = HorillaMailAttachment(
                mail=draft_mail,
                file=img_file,
                company=company,
                is_inline=True,
                content_id=cid,
            )
            attachment.save()

    def _handle_new_schedule(self, request):
        """Handle creation of a new scheduled mail."""
        errors = {}

        to_email = request.POST.get("to_email", "")
        cc_email = request.POST.get("cc_email", "")
        bcc_email = request.POST.get("bcc_email", "")
        subject = request.POST.get("subject", "")
        message_content = request.POST.get("message_content", "")
        from_mail_id = request.POST.get("from_mail")
        uploaded_files = request.FILES.getlist("attachments")
        scheduled_at = request.POST.get("schedule_datetime")

        model_name = request.GET.get("model_name")
        object_id = request.GET.get("object_id")
        pk = request.GET.get("pk")
        is_reschedule = False

        company = getattr(request, "active_company", None)
        setattr(_thread_local, "from_mail_id", from_mail_id)

        errors = self._validate_form_fields(
            to_email, from_mail_id, scheduled_at, message_content
        )

        if errors:
            return self._render_error_response(
                request, errors, model_name, object_id, pk, is_reschedule, scheduled_at
            )

        try:
            from_mail_config = HorillaMailConfiguration.objects.get(id=from_mail_id)
        except HorillaMailConfiguration.DoesNotExist:
            errors["from_mail"] = _("Invalid mail configuration selected")
            return self._render_error_response(
                request, errors, model_name, object_id, pk, is_reschedule, scheduled_at
            )

        content_type = None
        if model_name and object_id:
            try:
                content_type = ContentType.objects.get(model=model_name.lower())
            except ContentType.DoesNotExist:
                errors["non_field_error"] = f"Invalid model name: {model_name}"
                return self._render_error_response(
                    request,
                    errors,
                    model_name,
                    object_id,
                    pk,
                    is_reschedule,
                    scheduled_at,
                )

        schedule_at, _unused = self._validate_schedule_datetime(scheduled_at)

        draft_mail = self._get_or_create_draft_mail(
            request, pk, content_type, object_id, from_mail_config, company
        )

        request_info = {
            "host": request.get_host(),
            "scheme": request.scheme,
        }

        cleaned_message_content, inline_images = extract_inline_images_with_cid(
            message_content
        )

        draft_mail.sender = from_mail_config
        draft_mail.to = to_email
        draft_mail.cc = cc_email if cc_email else None
        draft_mail.bcc = bcc_email if bcc_email else None
        draft_mail.subject = subject if subject else None
        draft_mail.body = cleaned_message_content if cleaned_message_content else None
        draft_mail.mail_status = "scheduled"
        draft_mail.scheduled_at = schedule_at
        if draft_mail.additional_info is None:
            draft_mail.additional_info = {}
        draft_mail.additional_info["request_info"] = request_info
        draft_mail.save()

        self._save_mail_attachments(draft_mail, uploaded_files, inline_images, company)

        messages.success(
            request,
            _("Mail scheduled successfully for ")
            + schedule_at.strftime("%Y-%m-%d %H:%M"),
        )
        return HttpResponse(
            "<script>closehorillaModal();$('#scheduled-email-tab').click();closeModal();</script>"
        )

    def post(self, request, *args, **kwargs):
        """Handle scheduling mail - new or reschedule existing."""
        pk = kwargs.get("pk") or request.GET.get("pk")
        scheduled_at = request.POST.get("schedule_datetime")
        is_reschedule = bool(kwargs.get("pk"))

        if is_reschedule:
            return self._handle_reschedule(request, pk, scheduled_at)

        try:
            return self._handle_new_schedule(request)
        except Exception as e:
            import traceback

            logger.error(traceback.format_exc())
            model_name = request.GET.get("model_name")
            object_id = request.GET.get("object_id")
            pk = request.GET.get("pk")
            is_reschedule = False
            scheduled_at = request.POST.get("schedule_datetime", "")
            errors = {"non_field_error": _("Error scheduling mail: ") + str(e)}
            return self._render_error_response(
                request, errors, model_name, object_id, pk, is_reschedule, scheduled_at
            )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "horilla_mail.view_horillamailconfiguration",
            "horilla_mail.add_horillamailconfiguration",
        ]
    ),
    name="dispatch",
)
class ScheduleMailModallView(LoginRequiredMixin, View):
    """
    Open the schedule modal
    """

    def get(self, request, *args, **kwargs):
        """
        Render the schedule mail modal form"""
        model_name = request.GET.get("model_name")
        object_id = request.GET.get("object_id")
        pk = request.GET.get("pk") or kwargs.get("pk")
        is_reschedule = bool(kwargs.get("pk"))
        mail = HorillaMail.objects.get(pk=pk)
        scheduled_at_formatted = ""
        if mail.scheduled_at:
            user_tz = timezone.get_current_timezone()
            scheduled_at_local = mail.scheduled_at.astimezone(user_tz)
            scheduled_at_formatted = scheduled_at_local.strftime("%Y-%m-%dT%H:%M")

        context = {
            "model_name": model_name,
            "object_id": object_id,
            "pk": pk,
            "is_reschedule": is_reschedule,
            "scheduled_at": scheduled_at_formatted,
        }

        render_html = render_to_string(
            "schedule_mail_form.html", context, request=request
        )
        return HttpResponse(render_html)
