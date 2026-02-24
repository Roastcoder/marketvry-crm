"""
Forms for horilla_generics.

Contains form classes and helpers used across the horilla_generics app.
"""

# Standard library imports
import logging
from datetime import date, datetime
from decimal import Decimal

import bleach

# Django imports
from django import forms
from django.apps import apps
from django.db import models
from django.db.models import Q
from django.db.models.fields import Field
from django.db.models.fields.files import ImageFieldFile
from django.templatetags.static import static
from django.urls import reverse_lazy
from django.utils.encoding import force_str
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

# Third-party imports
from django_countries.fields import Country, CountryField
from django_summernote.widgets import SummernoteInplaceWidget

# Horilla application imports
from horilla.auth.models import User
from horilla_core.models import HorillaAttachment, KanbanGroupBy, ListColumnVisibility
from horilla_utils.middlewares import _thread_local

logger = logging.getLogger(__name__)


# Define your horilla_generics forms here
class KanbanGroupByForm(forms.ModelForm):
    """Form for configuring group-by settings for Kanban or Group By view."""

    class Meta:
        """Meta options for KanbanGroupByForm."""

        model = KanbanGroupBy
        fields = ["model_name", "field_name", "app_label", "view_type"]
        widgets = {
            "model_name": forms.HiddenInput(),
            "app_label": forms.HiddenInput(),
            "view_type": forms.HiddenInput(),
            "field_name": forms.Select(),
        }

    def __init__(self, *args, **kwargs):
        self.request = getattr(_thread_local, "request")
        exclude_fields = kwargs.pop("exclude_fields", [])
        include_fields = kwargs.pop("include_fields", [])
        super().__init__(*args, **kwargs)

        # Try to resolve model/app from data, then initial, then instance
        model_name = (
            self.data.get("model_name")
            or self.initial.get("model_name")
            or getattr(self.instance, "model_name", None)
        )
        app_label = (
            self.data.get("app_label")
            or self.initial.get("app_label")
            or getattr(self.instance, "app_label", None)
        )

        if model_name and app_label:
            temp_instance = KanbanGroupBy(model_name=model_name, app_label=app_label)
            user = getattr(self.request, "user", None) if self.request else None
            self.fields["field_name"].choices = temp_instance.get_model_groupby_fields(
                exclude_fields=exclude_fields,
                include_fields=include_fields,
                user=user,
            )
        else:
            self.fields["field_name"].choices = []

        view_type = (
            self.data.get("view_type")
            or self.initial.get("view_type")
            or getattr(self.instance, "view_type", "kanban")
        )
        self.fields["view_type"].initial = view_type

    def clean(self):
        cleaned_data = super().clean()
        model_name = cleaned_data.get("model_name")
        app_label = cleaned_data.get("app_label")
        field_name = cleaned_data.get("field_name")

        # Only validate if field_name is filled
        view_type = cleaned_data.get("view_type") or "kanban"
        if model_name and field_name:
            temp_instance = KanbanGroupBy(
                model_name=model_name,
                field_name=field_name,
                app_label=app_label,
                view_type=view_type,
                user=self.request.user,
            )
            try:
                temp_instance.clean()
            except Exception as e:
                self.add_error("field_name", e)

        return cleaned_data

    def validate_unique(self):
        pass


class ColumnSelectionForm(forms.Form):
    """Form for selecting visible columns in list views."""

    visible_fields = forms.MultipleChoiceField(
        required=False, widget=forms.MultipleHiddenInput
    )

    def __init__(self, *args, **kwargs):
        model = kwargs.pop("model", None)
        app_label = kwargs.pop("app_label", None)
        path_context = kwargs.pop("path_context", None)
        user = kwargs.pop("user", None)
        model_name = kwargs.pop("model_name", None)
        _url_name = kwargs.pop("url_name", None)
        super().__init__(*args, **kwargs)

        if model:
            excluded_fields = ["history"]
            # Get model fields and methods as [verbose_name, field_name]
            instance = model()
            model_fields = [
                [
                    force_str(f.verbose_name or f.name.title()),
                    (
                        f.name
                        if not getattr(f, "choices", None)
                        else f"get_{f.name}_display"
                    ),
                ]
                for f in model._meta.get_fields()
                if isinstance(f, Field) and f.name not in excluded_fields
            ]

            # Use columns property if available, otherwise use model_fields
            all_fields = (
                getattr(instance, "columns", model_fields)
                if hasattr(instance, "columns")
                else model_fields
            )
            field_name_to_verbose = {f[1]: f[0] for f in all_fields}
            unique_field_names = {f[1] for f in all_fields}

            visible_field_lists = []
            removed_custom_field_lists = []
            if app_label and model_name and path_context and user:
                visibility = ListColumnVisibility.all_objects.filter(
                    user=user,
                    app_label=app_label,
                    model_name=model_name,
                    context=path_context,
                ).first()
                if visibility:
                    visible_field_lists = visibility.visible_fields
                    removed_custom_field_lists = visibility.removed_custom_fields

            choices = [(f[1], f[0]) for f in all_fields]

            for visible_field in visible_field_lists:
                if (
                    len(visible_field) >= 2
                    and visible_field[1] not in unique_field_names
                ):
                    choices.append((visible_field[1], visible_field[0]))
                    unique_field_names.add(visible_field[1])
                    field_name_to_verbose[visible_field[1]] = visible_field[0]

            for custom_field in removed_custom_field_lists:
                if len(custom_field) >= 2 and custom_field[1] not in unique_field_names:
                    choices.append((custom_field[1], custom_field[0]))
                    unique_field_names.add(custom_field[1])
                    field_name_to_verbose[custom_field[1]] = custom_field[0]

            choices.sort(key=lambda x: x[1].lower())
            self.fields["visible_fields"].choices = choices

            if self.data:
                field_names = (
                    self.data.getlist("visible_fields")
                    if hasattr(self.data, "getlist")
                    else self.data.get("visible_fields", [])
                )
                if not isinstance(field_names, list):
                    field_names = [field_names] if field_names else []
                valid_field_names = [f for f in field_names if f in unique_field_names]
                if valid_field_names:
                    self.data = self.data.copy() if hasattr(self.data, "copy") else {}
                    if hasattr(self.data, "setlist"):
                        self.data.setlist("visible_fields", valid_field_names)
                    else:
                        self.data["visible_fields"] = valid_field_names


class HorillaMultiStepForm(forms.ModelForm):
    """Base form class for multi-step form workflows."""

    step_fields = {}

    def __init__(self, *args, **kwargs):
        self.current_step = int(kwargs.pop("step", 1))
        self.form_data = kwargs.pop("form_data", {}) or {}
        self.full_width_fields = kwargs.pop("full_width_fields", [])
        self.dynamic_create_fields = kwargs.pop("dynamic_create_fields", [])
        self.request = kwargs.pop("request", None)
        self.field_permissions = kwargs.pop("field_permissions", {})

        self.stored_files = {}

        super().__init__(*args, **kwargs)

        # Get all step fields to identify fields that should be excluded
        all_step_fields = []
        if hasattr(self, "step_fields") and self.step_fields:
            for step_fields_list in self.step_fields.values():
                all_step_fields.extend(step_fields_list)

        # Remove ManyToMany fields that are not in any step from the form
        # (like groups, user_permissions in User form)
        if all_step_fields:
            fields_to_remove = []
            for field_name, field in list(self.fields.items()):
                if field_name not in all_step_fields:
                    try:
                        model_field = self._meta.model._meta.get_field(field_name)
                        if isinstance(model_field, models.ManyToManyField):
                            fields_to_remove.append(field_name)
                    except models.FieldDoesNotExist:
                        pass

            for field_name in fields_to_remove:
                del self.fields[field_name]

        # Store original required state before any modifications
        for field_name, field in self.fields.items():
            field._original_required = field.required
            if isinstance(field.widget, forms.CheckboxInput):
                field.required = False

        if self.request and self.request.FILES:
            self.files = self.request.FILES

        if hasattr(self, "files") and self.files:
            for field_name, file_obj in self.files.items():
                self.stored_files[field_name] = file_obj

        # Get all step fields to check if a field should be processed
        all_step_fields = []
        if hasattr(self, "step_fields") and self.step_fields:
            for step_fields_list in self.step_fields.values():
                all_step_fields.extend(step_fields_list)

        if self.instance and self.instance.pk:
            for field_name in self.fields:
                if all_step_fields and field_name not in all_step_fields:
                    try:
                        model_field = self._meta.model._meta.get_field(field_name)
                        if isinstance(model_field, models.ManyToManyField):
                            continue
                    except models.FieldDoesNotExist:
                        # If we can't determine the field type, process it to be safe
                        pass

                if field_name not in self.form_data or self.form_data[field_name] in [
                    None,
                    "",
                    [],
                ]:
                    field_value = getattr(self.instance, field_name, None)
                    if field_value is not None:
                        if hasattr(field_value, "pk"):
                            self.form_data[field_name] = field_value.pk
                        elif hasattr(field_value, "all"):
                            # Only populate ManyToMany if field is in at least one step
                            if not all_step_fields or field_name in all_step_fields:
                                self.form_data[field_name] = [
                                    obj.pk for obj in field_value.all()
                                ]
                        elif isinstance(field_value, datetime):
                            self.form_data[field_name] = field_value.strftime(
                                "%Y-%m-%dT%H:%M"
                            )
                        elif isinstance(field_value, date):
                            self.form_data[field_name] = field_value.strftime(
                                "%Y-%m-%d"
                            )
                        elif isinstance(field_value, Decimal):
                            self.form_data[field_name] = str(field_value)
                        elif isinstance(field_value, bool):
                            self.form_data[field_name] = field_value
                        elif isinstance(field_value, Country):
                            self.form_data[field_name] = str(field_value)
                        elif isinstance(field_value, (ImageFieldFile)):
                            # For existing files, we need to preserve the file info
                            if field_value.name:
                                self.form_data[field_name] = field_value.name
                                # Only set filename if not already set from session
                                if f"{field_name}_filename" not in self.form_data:
                                    self.form_data[f"{field_name}_filename"] = (
                                        field_value.name.split("/")[-1]
                                    )
                        else:
                            self.form_data[field_name] = field_value

        if self.form_data:
            # Clean up form data to ensure proper formatting for date/datetime fields
            cleaned_form_data = {}
            for field_name, field_value in self.form_data.items():
                if field_name in self.fields:
                    try:
                        model_field = self._meta.model._meta.get_field(field_name)
                        if isinstance(model_field, models.BooleanField):
                            # Convert string values to boolean
                            if isinstance(field_value, str):
                                cleaned_form_data[field_name] = field_value.lower() in (
                                    "true",
                                    "on",
                                    "1",
                                )
                            else:
                                cleaned_form_data[field_name] = bool(field_value)
                        elif isinstance(
                            model_field, models.DateField
                        ) and not isinstance(model_field, models.DateTimeField):
                            if isinstance(field_value, str) and "T" in field_value:
                                cleaned_form_data[field_name] = field_value.split("T")[
                                    0
                                ]
                            elif isinstance(field_value, (datetime, date)):
                                cleaned_form_data[field_name] = field_value.strftime(
                                    "%Y-%m-%d"
                                )
                            else:
                                cleaned_form_data[field_name] = field_value
                        elif isinstance(model_field, models.DateTimeField):
                            if isinstance(field_value, str) and "T" not in field_value:
                                cleaned_form_data[field_name] = f"{field_value}T00:00"
                            elif isinstance(field_value, datetime):
                                cleaned_form_data[field_name] = field_value.strftime(
                                    "%Y-%m-%dT%H:%M"
                                )
                            elif isinstance(field_value, date):
                                cleaned_form_data[field_name] = (
                                    f"{field_value.strftime('%Y-%m-%d')}T00:00"
                                )
                            else:
                                cleaned_form_data[field_name] = field_value
                        elif isinstance(model_field, CountryField):
                            cleaned_form_data[field_name] = str(field_value)
                        else:
                            cleaned_form_data[field_name] = field_value
                    except models.FieldDoesNotExist:
                        cleaned_form_data[field_name] = field_value
                else:
                    cleaned_form_data[field_name] = field_value

            self.data = cleaned_form_data

        self._configure_field_widgets()

        # Apply field permissions: remove hidden fields and readonly fields in create mode FIRST
        # Do this BEFORE step-specific field visibility to ensure mandatory fields are preserved
        if self.field_permissions:
            # Check if we're in create mode
            is_create_mode = not (self.instance and self.instance.pk)

            fields_to_remove = []
            for field_name, field in list(self.fields.items()):
                # Skip fields that are already hidden
                if isinstance(field.widget, forms.HiddenInput):
                    continue

                permission = self.field_permissions.get(field_name, "readwrite")

                # Remove hidden fields
                if permission == "hidden":
                    # In create mode, don't hide mandatory fields (user needs to fill them)
                    if is_create_mode:
                        # Check if field is mandatory (required) - check model field directly
                        is_mandatory = False
                        try:
                            model_field = self._meta.model._meta.get_field(field_name)
                            # Field is mandatory if it doesn't allow null and doesn't allow blank
                            is_mandatory = (
                                not model_field.null and not model_field.blank
                            )
                        except Exception:
                            # If we can't get the model field, check form field's required attribute
                            is_mandatory = getattr(
                                field, "_original_required", field.required
                            )

                        # Only hide if NOT mandatory in create mode
                        if not is_mandatory:
                            fields_to_remove.append(field_name)
                    else:
                        # In edit mode, always hide fields with "hidden" permission
                        fields_to_remove.append(field_name)
                # In create mode, hide readonly fields ONLY if they are NOT mandatory
                elif permission == "readonly" and is_create_mode:
                    # Check if field is mandatory (required) - check model field directly
                    is_mandatory = False
                    try:
                        model_field = self._meta.model._meta.get_field(field_name)
                        # Field is mandatory if it doesn't allow null and doesn't allow blank
                        is_mandatory = not model_field.null and not model_field.blank
                    except Exception:
                        # If we can't get the model field, check form field's required attribute
                        is_mandatory = getattr(
                            field, "_original_required", field.required
                        )

                    # Only hide readonly fields if they are NOT mandatory
                    # Mandatory readonly fields should be shown in create mode (editable)
                    if not is_mandatory:
                        fields_to_remove.append(field_name)

            # Remove fields
            for field_name in fields_to_remove:
                if field_name in self.fields:
                    del self.fields[field_name]

        # Handle step-specific field visibility FIRST
        # This must happen before applying readonly attributes so we only apply them to visible fields
        # IMPORTANT: Don't hide mandatory readonly fields even if they're not in current step
        # But only preserve mandatory readonly fields from current step or earlier steps, not future steps
        if self.current_step <= len(self.step_fields):
            current_fields = self.step_fields.get(self.current_step, [])
            all_step_fields = [
                f for step_fields in self.step_fields.values() for f in step_fields
            ]
            is_create_mode = not (self.instance and self.instance.pk)

            # Get fields from current and earlier steps (for mandatory readonly fields)
            current_and_earlier_fields = []
            if hasattr(self, "step_fields") and self.step_fields:
                for step_num in range(1, self.current_step + 1):
                    if step_num in self.step_fields:
                        current_and_earlier_fields.extend(self.step_fields[step_num])

            for field_name in self.fields:
                # Check if field is mandatory readonly/hidden - don't hide it in create mode
                # But only if it belongs to the CURRENT step (not earlier steps)
                # Mandatory readonly fields should only appear in their own step, not in later steps
                is_mandatory_readonly = False
                if (
                    is_create_mode
                    and hasattr(self, "field_permissions")
                    and self.field_permissions
                ):
                    permission = self.field_permissions.get(field_name, "readwrite")
                    if permission in ("readonly", "hidden"):
                        # Only preserve mandatory readonly fields that are in the CURRENT step
                        # Don't preserve them if they're from earlier steps - they should only appear in their own step
                        if field_name in current_fields:
                            try:
                                model_field = self._meta.model._meta.get_field(
                                    field_name
                                )
                                is_mandatory_readonly = (
                                    not model_field.null and not model_field.blank
                                )
                            except Exception:
                                is_mandatory_readonly = getattr(
                                    self.fields[field_name],
                                    "_original_required",
                                    self.fields[field_name].required,
                                )

                # If field is not in any step, but it's mandatory readonly/hidden in create mode, keep it visible
                if field_name not in all_step_fields:
                    if not is_mandatory_readonly:
                        self.fields[field_name].required = False
                        self.fields[field_name].widget = forms.HiddenInput()
                    continue

                # If field is not in current step
                if field_name not in current_fields:
                    # Don't hide mandatory readonly/hidden fields in create mode
                    # But only if they belong to current or earlier steps
                    if not is_mandatory_readonly:
                        self.fields[field_name].required = False
                        self.fields[field_name].widget = forms.HiddenInput()
                else:
                    try:
                        original_field = self._meta.model._meta.get_field(field_name)
                        if isinstance(original_field, models.BooleanField):
                            self.fields[field_name].required = False
                        elif hasattr(original_field, "blank"):
                            if isinstance(
                                original_field, (models.FileField, models.ImageField)
                            ):
                                # Check if we have existing file, new file, or stored file
                                has_existing_file = (
                                    self.instance
                                    and self.instance.pk
                                    and getattr(self.instance, field_name, None)
                                )
                                has_new_file = field_name in self.stored_files
                                has_stored_filename = (
                                    f"{field_name}_filename" in self.form_data
                                )

                                # Only make not required if we actually have a file AND field allows blank
                                if (
                                    has_existing_file
                                    or has_new_file
                                    or has_stored_filename
                                ) and original_field.blank:
                                    self.fields[field_name].required = False
                                else:
                                    # Keep original required setting
                                    self.fields[field_name].required = (
                                        not original_field.blank
                                    )
                            else:
                                self.fields[field_name].required = (
                                    not original_field.blank
                                )
                    except models.FieldDoesNotExist:
                        pass

        # Apply field permissions: readonly attributes (AFTER step-specific visibility)
        # This ensures readonly attributes are only applied to visible fields in the current step
        # IMPORTANT: Apply to ALL fields first, then step-specific visibility will hide non-current step fields
        # But readonly attributes will remain on fields that are visible in the current step
        if self.field_permissions:
            # Check if we're in create mode
            is_create_mode = not (self.instance and self.instance.pk)

            # Get current step fields to ensure we apply readonly to fields in current step
            current_fields = []
            if hasattr(self, "step_fields") and self.current_step in self.step_fields:
                current_fields = self.step_fields.get(self.current_step, [])

            for field_name, field in self.fields.items():
                # Skip fields that are hidden (but only if they're not in current step)
                # If field is in current step, it shouldn't be hidden, so apply readonly
                if isinstance(field.widget, forms.HiddenInput):
                    # Only skip if it's truly hidden (not in current step)
                    if field_name not in current_fields:
                        continue
                    # If it's in current step but hidden, restore it first
                    # This shouldn't happen, but just in case

                permission = self.field_permissions.get(field_name, "readwrite")

                if permission == "readonly":
                    # Check if we should skip making it readonly in create mode for mandatory fields
                    is_mandatory = False
                    try:
                        model_field = self._meta.model._meta.get_field(field_name)
                        is_mandatory = not model_field.null and not model_field.blank
                    except Exception:
                        is_mandatory = field.required

                    # In create mode, if field is mandatory, don't make it readonly
                    if is_create_mode and is_mandatory:
                        continue  # Skip making it readonly - user needs to fill it

                    # Apply readonly/disabled based on field type
                    try:
                        model_field = self._meta.model._meta.get_field(field_name)
                    except Exception:
                        model_field = None

                    # Check if it's a select field (ForeignKey, ManyToMany, or ChoiceField)
                    is_select_field = (
                        isinstance(field.widget, (forms.Select, forms.SelectMultiple))
                        or (
                            model_field
                            and isinstance(
                                model_field, (models.ForeignKey, models.ManyToManyField)
                            )
                        )
                        or (
                            model_field
                            and hasattr(model_field, "choices")
                            and model_field.choices
                        )
                    )

                    if is_select_field:
                        # For select fields, use disabled
                        field.disabled = True
                        if not hasattr(field.widget, "attrs"):
                            field.widget.attrs = {}
                        field.widget.attrs["disabled"] = "disabled"
                        field.widget.attrs["data-disabled"] = "true"
                        # Add styling - preserve existing classes
                        existing_class = field.widget.attrs.get("class", "")
                        if "bg-gray-100" not in existing_class:
                            field.widget.attrs["class"] = (
                                f"{existing_class} bg-gray-100 cursor-not-allowed opacity-60".strip()
                            )
                    else:
                        # For text fields, use readonly
                        if not hasattr(field.widget, "attrs"):
                            field.widget.attrs = {}
                        field.widget.attrs["readonly"] = "readonly"
                        field.widget.attrs["data-readonly"] = "true"
                        field.disabled = False
                        # Add styling - preserve existing classes
                        existing_class = field.widget.attrs.get("class", "")
                        if "bg-gray-200" not in existing_class:
                            field.widget.attrs["class"] = (
                                f"{existing_class} bg-gray-200 border-gray-300 cursor-not-allowed opacity-75".strip()
                            )
                        field.widget.attrs["tabindex"] = "-1"

    def get_fields_for_step(self, step):
        """
        Returns form fields for the given step, including mandatory readonly/hidden fields in create mode
        Only includes mandatory readonly/hidden fields that belong to the current step or earlier steps
        """
        # Get all step fields across all steps
        all_step_fields = []
        if hasattr(self, "step_fields") and self.step_fields:
            for step_fields_list in self.step_fields.values():
                all_step_fields.extend(step_fields_list)

        current_fields = []
        if hasattr(self, "step_fields") and step in self.step_fields:
            current_fields = self.step_fields.get(step, [])

        # Get fields from current and earlier steps (for mandatory readonly fields)
        current_and_earlier_fields = []
        if hasattr(self, "step_fields") and self.step_fields:
            for step_num in range(1, step + 1):
                if step_num in self.step_fields:
                    current_and_earlier_fields.extend(self.step_fields[step_num])

        fields_list = []

        # Check if we're in create mode
        _is_create_mode = not (self.instance and self.instance.pk)

        # Add fields from current step
        for field_name in current_fields:
            if field_name in self.fields:
                field = self[field_name]
                fields_list.append(field)

        # In create mode, DON'T include mandatory readonly/hidden fields from earlier steps
        # Mandatory readonly fields should only appear in their own step, not in later steps
        # They are already included above when we iterate through current_fields
        # This section is intentionally left empty to prevent mandatory readonly fields from appearing in later steps

        # If no step_fields defined, return all visible fields
        if not hasattr(self, "step_fields") or not self.step_fields:
            return self.visible_fields()

        return fields_list

    def _configure_field_widgets(self):
        """Configure widgets for all form fields with pagination support"""
        for field_name, field in self.fields.items():
            widget_attrs = {
                "class": "text-color-600 p-2 placeholder:text-xs  w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
            }

            if field_name in self.full_width_fields:
                widget_attrs["fullwidth"] = True

            # Get the model field to determine its type
            try:
                model_field = self._meta.model._meta.get_field(field_name)
            except models.FieldDoesNotExist:
                model_field = None

            if model_field:
                if isinstance(model_field, (models.ImageField, models.FileField)):
                    # Check if we have existing file or new file
                    has_existing_file = (
                        self.instance
                        and self.instance.pk
                        and getattr(self.instance, field_name, None)
                    )
                    has_new_file = field_name in self.stored_files

                    # Only make field not required if we have an existing/new file AND field allows blank
                    # AND we're not in the current step OR we have a file
                    current_fields = self.step_fields.get(self.current_step, [])
                    if field_name not in current_fields:
                        # Not in current step, make not required
                        field.required = False
                    elif (has_existing_file or has_new_file) and model_field.blank:
                        # In current step but has file and field allows blank
                        field.required = False
                    else:
                        # In current step, respect original field requirements
                        field.required = not model_field.blank

                    if isinstance(model_field, models.ImageField):
                        field.widget.attrs["accept"] = "image/*"

                    field.widget.attrs["formnovalidate"] = "formnovalidate"

                    if not field.widget.attrs.get("placeholder"):
                        field_label = (
                            field.label or field_name.replace("_", " ").title()
                        )
                        widget_attrs["placeholder"] = _("Upload %(field)s") % {
                            "field": field_label
                        }

                elif isinstance(model_field, models.DateField) and not isinstance(
                    model_field, models.DateTimeField
                ):
                    field.widget = forms.DateInput(
                        attrs={"type": "date"}, format="%Y-%m-%d"
                    )
                    field.input_formats = ["%Y-%m-%d"]

                elif isinstance(model_field, models.DateTimeField):
                    field.widget = forms.DateTimeInput(
                        attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
                    )
                    field.input_formats = [
                        "%Y-%m-%dT%H:%M",
                        "%Y-%m-%d %H:%M:%S",
                        "%Y-%m-%d %H:%M",
                    ]
                elif isinstance(model_field, models.TimeField):
                    if not isinstance(field.widget, forms.HiddenInput):
                        field.widget = forms.TimeInput(
                            attrs={
                                "type": "time",
                                "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                            }
                        )

                elif isinstance(model_field, models.ManyToManyField):
                    # Only configure ManyToMany fields that are in at least one step
                    # Skip fields not in any step (like groups, user_permissions in User form)
                    all_step_fields = []
                    if hasattr(self, "step_fields") and self.step_fields:
                        for step_fields_list in self.step_fields.values():
                            all_step_fields.extend(step_fields_list)

                    if field_name in all_step_fields:
                        self._configure_many_to_many_field(
                            field, field_name, model_field
                        )
                    else:
                        # Field not in any step - hide it or make it not required
                        # Don't configure pagination for it
                        field.required = False
                        if not isinstance(field.widget, forms.HiddenInput):
                            field.widget = forms.HiddenInput()

                elif isinstance(model_field, models.ForeignKey):
                    self._configure_foreign_key_field(field, field_name, model_field)

                elif isinstance(model_field, models.TextField):
                    field.widget = forms.Textarea()
                    if not field.widget.attrs.get("placeholder"):
                        field_label = (
                            field.label or field_name.replace("_", " ").title()
                        )
                        widget_attrs["placeholder"] = _("Enter %(field)s") % {
                            "field": field_label
                        }

                elif isinstance(model_field, models.BooleanField):
                    field.widget = forms.CheckboxInput()

                else:
                    # For all other field types, use generic placeholder
                    if not field.widget.attrs.get("placeholder"):
                        field_label = (
                            field.label or field_name.replace("_", " ").title()
                        )
                        widget_attrs["placeholder"] = _("Enter %(field)s") % {
                            "field": field_label
                        }
            else:
                # If no model field found, use generic placeholder
                if not field.widget.attrs.get("placeholder"):
                    field_label = field.label or field_name.replace("_", " ").title()
                    widget_attrs["placeholder"] = _("Enter %(field)s") % {
                        "field": field_label
                    }

            # Apply widget-specific classes and attributes
            if isinstance(field.widget, forms.Select):
                widget_attrs["class"] += " js-example-basic-single headselect"
            elif isinstance(field.widget, forms.Textarea):
                widget_attrs["class"] += " w-full"
            elif isinstance(field.widget, forms.CheckboxInput):
                widget_attrs["class"] = "sr-only peer"
            elif isinstance(field.widget, (forms.DateInput, forms.DateTimeInput)):
                # Don't add placeholder to date/datetime inputs
                if "placeholder" in widget_attrs:
                    del widget_attrs["placeholder"]

            if not hasattr(field.widget, "_pagination_configured"):
                field.widget.attrs.update(widget_attrs)

    def _configure_many_to_many_field(self, field, field_name, model_field):
        """Configure ManyToManyField with pagination support"""
        related_model = model_field.related_model
        app_label = related_model._meta.app_label
        model_name = related_model._meta.model_name

        initial_value = []
        # When editing, prioritize instance values over form_data to avoid losing data
        # when field is not in current step
        if self.instance and self.instance.pk:
            # Get values from instance first
            try:
                initial_value = list(
                    getattr(self.instance, field_name).values_list("pk", flat=True)
                )
                # Only override with form_data if it has actual values (not empty list)
                if field_name in self.form_data:
                    form_data_value = self.form_data[field_name]
                    # Handle case where form_data contains string representation of list
                    # (happens when session serializes lists)
                    if isinstance(form_data_value, list) and len(form_data_value) == 1:
                        first_item = form_data_value[0]
                        # Check if it's a string that looks like a list representation
                        if isinstance(first_item, str) and (
                            first_item.startswith("[") and first_item.endswith("]")
                        ):
                            try:
                                import ast

                                parsed_list = ast.literal_eval(first_item)
                                if isinstance(parsed_list, list) and parsed_list:
                                    initial_value = parsed_list
                                elif isinstance(parsed_list, list) and not parsed_list:
                                    # Empty list from string '[]', keep instance values
                                    pass
                                else:
                                    initial_value = [parsed_list] if parsed_list else []
                            except (ValueError, SyntaxError):
                                # Failed to parse, keep instance values
                                pass
                        elif form_data_value:
                            # Normal list with actual values
                            initial_value = form_data_value
                    elif isinstance(form_data_value, list) and form_data_value:
                        # form_data has values, use them
                        initial_value = form_data_value
                    elif form_data_value and not isinstance(form_data_value, list):
                        initial_value = [form_data_value]
                    # If form_data_value is empty list [], keep instance values
            except Exception:
                # If instance doesn't have the field or error, fall back to form_data
                if field_name in self.form_data:
                    form_data_value = self.form_data[field_name]
                    if isinstance(form_data_value, list):
                        initial_value = form_data_value
                    elif form_data_value:
                        initial_value = [form_data_value]
        elif field_name in self.form_data:
            # Creating new instance - use form_data
            form_data_value = self.form_data[field_name]
            # Handle case where form_data contains string representation of list
            if isinstance(form_data_value, list) and len(form_data_value) == 1:
                first_item = form_data_value[0]
                # Check if it's a string that looks like a list representation
                if isinstance(first_item, str) and (
                    first_item.startswith("[") and first_item.endswith("]")
                ):
                    try:
                        import ast

                        parsed_list = ast.literal_eval(first_item)
                        if isinstance(parsed_list, list):
                            initial_value = parsed_list
                        else:
                            initial_value = [parsed_list] if parsed_list else []
                    except (ValueError, SyntaxError):
                        initial_value = []
                else:
                    initial_value = form_data_value
            elif isinstance(form_data_value, list):
                initial_value = form_data_value
            elif form_data_value:
                initial_value = [form_data_value]
            else:
                initial_value = []
        elif field_name in self.initial:
            # Fall back to initial data
            initial_data = self.initial[field_name]
            if isinstance(initial_data, list):
                initial_value = []
                for item in initial_data:
                    if hasattr(item, "pk"):
                        initial_value.append(item.pk)
                    else:
                        initial_value.append(item)
            else:
                if hasattr(initial_data, "pk"):
                    initial_value = [initial_data.pk]
                else:
                    initial_value = [initial_data]

        # Clean up and convert initial_value to integers
        # Handle case where initial_value might be a string representation of a list
        if initial_value:
            # If initial_value is a string that looks like a list, try to parse it
            if isinstance(initial_value, str):
                try:
                    import ast

                    initial_value = ast.literal_eval(initial_value)
                except (ValueError, SyntaxError):
                    # If parsing fails, treat as comma-separated string
                    initial_value = [
                        v.strip() for v in initial_value.split(",") if v.strip()
                    ]

            # Ensure it's a list
            if not isinstance(initial_value, list):
                initial_value = [initial_value] if initial_value else []

            # Convert all values to integers and filter out invalid ones
            cleaned_value = []
            for val in initial_value:
                if val is None or val == "" or val == []:
                    continue
                try:
                    # Convert to int if it's a string or already an int
                    int_val = int(val) if val else None
                    if int_val is not None:
                        cleaned_value.append(int_val)
                except (ValueError, TypeError):
                    # Skip invalid values
                    continue

            initial_value = cleaned_value
        else:
            initial_value = []

        # Get the selected objects for initial display
        initial_choices = []
        if initial_value:
            try:
                selected_objects = related_model.objects.filter(pk__in=initial_value)
                initial_choices = [(obj.pk, str(obj)) for obj in selected_objects]
            except Exception as e:
                logger.error(
                    "Error loading initial choices for %s: %s", field_name, str(e)
                )

        attrs = {
            "class": "select2-pagination w-full text-sm",
            "data-url": reverse_lazy(
                f"horilla_generics:model_select2",
                kwargs={"app_label": app_label, "model_name": model_name},
            ),
            "data-placeholder": _("Select %(field)s")
            % {"field": model_field.verbose_name.title()},
            "multiple": "multiple",
            "data-initial": (
                ",".join(map(str, initial_value)) if initial_value else ""
            ),
            "data-field-name": field_name,
            "id": f"id_{field_name}",
            "data-form-class": f"{self.__module__}.{self.__class__.__name__}",
        }
        if self.__class__.__name__ == "DynamicForm":
            attrs["data-parent-model"] = (
                f"{self._meta.model._meta.app_label}.{self._meta.model._meta.model_name}"
            )
        field.widget = forms.SelectMultiple(
            choices=initial_choices,
            attrs=attrs,
        )
        field.widget._pagination_configured = True

    def _configure_foreign_key_field(self, field, field_name, model_field):
        """Configure ForeignKey field with pagination support"""
        related_model = model_field.related_model
        app_label = related_model._meta.app_label
        model_name = related_model._meta.model_name

        # Get initial value properly
        initial_value = None
        if self.instance and self.instance.pk:
            related_obj = getattr(self.instance, field_name, None)
            initial_value = related_obj.pk if related_obj else None
        elif field_name in self.initial:
            initial_data = self.initial[field_name]
            if hasattr(initial_data, "pk"):
                initial_value = initial_data.pk
            else:
                initial_value = initial_data
        elif field_name in self.form_data:
            initial_value = self.form_data[field_name]

        # Get the selected object for initial display
        initial_choices = []
        if initial_value:
            try:
                selected_object = related_model.objects.get(pk=initial_value)
                initial_choices = [(selected_object.pk, str(selected_object))]
            except related_model.DoesNotExist:
                # Object doesn't exist (may have been deleted) - clear invalid value
                # This is not a critical error, just log as warning
                logger.warning(
                    "Initial object not found for %s: %s (object may have been deleted)",
                    field_name,
                    initial_value,
                )
                # Clear invalid value from form_data to prevent issues
                if (
                    field_name in self.form_data
                    and self.form_data[field_name] == initial_value
                ):
                    self.form_data[field_name] = None
                initial_value = None
            except Exception as e:
                logger.error(
                    "Error loading initial choice for %s: %s", field_name, str(e)
                )
                initial_value = None

        # Get object_id if editing
        object_id = None
        if self.instance and self.instance.pk:
            object_id = self.instance.pk

        attrs = {
            "class": "select2-pagination w-full",
            "data-url": reverse_lazy(
                f"horilla_generics:model_select2",
                kwargs={"app_label": app_label, "model_name": model_name},
            ),
            "data-placeholder": _("Select %(field)s")
            % {"field": model_field.verbose_name.title()},
            "data-initial": str(initial_value) if initial_value is not None else "",
            "data-field-name": field_name,  # Add unique identifier
            "id": f"id_{field_name}",
            "data-form-class": f"{self.__module__}.{self.__class__.__name__}",
        }
        if object_id:
            attrs["data-object-id"] = str(object_id)
        # For DynamicForm: pass parent model so Select2 can resolve form via
        # get_dynamic_form_for_model (form is not importable). Works for any model.
        if self.__class__.__name__ == "DynamicForm":
            attrs["data-parent-model"] = (
                f"{self._meta.model._meta.app_label}.{self._meta.model._meta.model_name}"
            )
        field.widget = forms.Select(
            choices=[("", "---------")] + initial_choices,  # Set initial choices
            attrs=attrs,
        )
        field.widget._pagination_configured = True

    def clean(self):
        cleaned_data = super().clean()

        # SECURITY: Prevent readonly fields from being changed - restore original values
        # This prevents users from removing readonly attribute in browser and editing the field
        if hasattr(self, "field_permissions") and self.field_permissions:
            # Only validate in edit mode (when instance exists)
            if self.instance and self.instance.pk:
                for field_name, permission in self.field_permissions.items():
                    if permission == "readonly" and field_name in self.fields:
                        # Get the model field to determine the type
                        try:
                            model_field = self._meta.model._meta.get_field(field_name)
                        except Exception:
                            # Field might not exist in model (could be a property)
                            continue

                        # Get original value from instance
                        if isinstance(model_field, models.ManyToManyField):
                            # ManyToMany field
                            original_value = list(
                                getattr(self.instance, field_name).all()
                            )
                        elif isinstance(model_field, models.ForeignKey):
                            # ForeignKey field
                            original_value = getattr(self.instance, field_name, None)
                        else:
                            # Regular field (CharField, IntegerField, etc.)
                            original_value = getattr(self.instance, field_name, None)

                        # Check if the value was changed
                        submitted_value = cleaned_data.get(field_name)
                        value_changed = False

                        if isinstance(model_field, models.ManyToManyField):
                            # Compare ManyToMany by comparing lists of PKs
                            original_pks = (
                                set([obj.pk for obj in original_value])
                                if original_value
                                else set()
                            )
                            submitted_pks = (
                                set([obj.pk for obj in submitted_value])
                                if submitted_value
                                else set()
                            )
                            value_changed = original_pks != submitted_pks
                        elif isinstance(model_field, models.ForeignKey):
                            # Compare ForeignKey by comparing PKs
                            original_pk = original_value.pk if original_value else None
                            submitted_pk = (
                                submitted_value.pk if submitted_value else None
                            )
                            value_changed = original_pk != submitted_pk
                        else:
                            # Compare regular fields
                            value_changed = original_value != submitted_value

                        # If value was changed, restore original and add validation error
                        if value_changed:
                            cleaned_data[field_name] = original_value
                            self.add_error(
                                field_name,
                                forms.ValidationError(
                                    _(
                                        "This field is read-only and cannot be modified."
                                    ),
                                    code="readonly_field",
                                ),
                            )
                        else:
                            # Ensure original value is set even if not changed
                            cleaned_data[field_name] = original_value

        current_fields = self.step_fields.get(self.current_step, [])

        errors_to_remove = []
        for field_name in list(self.errors.keys()):
            if field_name not in current_fields:
                errors_to_remove.append(field_name)

        for field_name in errors_to_remove:
            if field_name in self.errors:
                del self.errors[field_name]

        # For current step fields, handle file field validation properly
        for field_name in current_fields:
            if field_name in self.fields:
                try:
                    model_field = self._meta.model._meta.get_field(field_name)
                    if isinstance(model_field, (models.FileField, models.ImageField)):
                        has_stored_file = field_name in self.stored_files
                        has_existing_file = (
                            self.instance
                            and self.instance.pk
                            and getattr(self.instance, field_name, None)
                        )
                        has_form_data_file = (
                            field_name + "_filename" in self.form_data
                            or field_name + "_new_file" in self.form_data
                        )

                        # If field is required and no file exists, ensure error is present
                        if not model_field.blank and not (
                            has_stored_file or has_existing_file or has_form_data_file
                        ):
                            # Add required error if not already present
                            if field_name not in self.errors:
                                self.add_error(field_name, "This field is required.")
                        elif (
                            model_field.blank
                            or has_stored_file
                            or has_existing_file
                            or has_form_data_file
                        ):
                            # Remove error if field allows blank or has file
                            if field_name in self.errors:
                                # Only remove required errors, keep format/other validation errors
                                error_messages = self.errors[field_name].as_data()
                                non_required_errors = [
                                    error
                                    for error in error_messages
                                    if error.code != "required"
                                ]
                                if non_required_errors:
                                    # Keep non-required errors
                                    self.errors[field_name] = forms.ValidationError(
                                        non_required_errors
                                    )
                                else:
                                    # Remove all errors if only required errors
                                    del self.errors[field_name]
                except models.FieldDoesNotExist:
                    pass

        return cleaned_data


class SaveFilterListForm(forms.Form):
    """Form for saving filter configurations as reusable filter lists."""

    list_name = forms.CharField(
        max_length=100,
        required=True,
        label="List View Name",
        widget=forms.TextInput(
            attrs={
                "class": "text-color-600 p-2 placeholder:text-xs  w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                "placeholder": "Specify the list view name",
            }
        ),
    )
    model_name = forms.CharField(
        max_length=100, required=True, widget=forms.HiddenInput()
    )
    main_url = forms.CharField(required=False, widget=forms.HiddenInput())
    saved_list_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    make_public = forms.BooleanField(
        required=False,
        initial=False,
        label="Make as public",
        widget=forms.CheckboxInput(
            attrs={
                "class": "w-4 h-4 bg-[#E9EDF7] rounded-sm accent-[#e54f38]",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        list_name = cleaned_data.get("list_name")
        if not list_name or not list_name.strip():
            self.add_error("list_name", "List name cannot be empty.")
        return cleaned_data


class PasswordInputWithEye(forms.PasswordInput):
    """Password input widget with eye icon toggle for showing/hiding password."""

    def __init__(self, attrs=None):
        default_attrs = {
            "class": "text-color-600 p-2 placeholder:text-xs font-normal w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm transition duration-300 focus:border-primary-600 pr-10",
        }
        if attrs:
            default_attrs.update(attrs)
        super().__init__(attrs=default_attrs)

    def render(self, name, value, attrs=None, renderer=None):
        password_input = super().render(name, value, attrs, renderer)

        eye_toggle = f"""
        <div class="relative">
            {password_input}
            <button type="button" class="absolute inset-y-0 right-0 pr-3 flex items-center"onclick="togglePassword('{attrs.get('id', name)}')">
                <img id="eye-icon-{attrs.get('id', name)}" src="/static/assets/icons/eye-hide.svg" alt="Toggle Password" class="w-4 h-4 text-gray-400 hover:text-gray-600 cursor-pointer" />
            </button>
        </div>
        <script>
        function togglePassword(fieldId) {{
            const passwordField = document.getElementById(fieldId);
            const eyeIcon = document.getElementById('eye-icon-' + fieldId);
            if (passwordField.type === 'password') {{
                passwordField.type = 'text';
                eyeIcon.src = '/static/assets/icons/eye.svg';
            }} else {{
                passwordField.type = 'password';
                eyeIcon.src = '/static/assets/icons/eye-hide.svg';
            }}
        }}
        </script>
        """

        return mark_safe(eye_toggle)


class HorillaModelForm(forms.ModelForm):
    """Base model form class with enhanced field configuration and validation."""

    def __init__(self, *args, **kwargs):
        self.full_width_fields = kwargs.pop("full_width_fields", [])
        self.dynamic_create_fields = kwargs.pop("dynamic_create_fields", [])
        self.hidden_fields = kwargs.pop("hidden_fields", [])
        self.condition_fields = kwargs.pop("condition_fields", [])
        self.condition_model = kwargs.pop("condition_model", None)
        self.condition_hx_include = kwargs.pop("condition_hx_include", "")
        self.request = kwargs.pop("request", None)
        self.field_permissions = kwargs.pop("field_permissions", {})
        self.save_and_new = kwargs.pop("save_and_new", "")
        # Get duplicate_mode to determine if readonly fields should be hidden
        self.duplicate_mode = kwargs.pop("duplicate_mode", False)
        self.row_id = kwargs.pop("row_id", "0")
        self.instance_obj = kwargs.get(
            "instance"
        )  # Store instance for condition methods

        # Get model_name from kwargs, request, or instance (generic extraction)
        self.model_name = kwargs.pop("model_name", None)
        if not self.model_name:
            self.model_name = self._get_model_name_from_request_or_instance(kwargs)

        # Build condition_field_choices automatically if condition_model is provided
        condition_field_choices = kwargs.pop("condition_field_choices", None)
        if (
            not condition_field_choices
            and self.condition_model
            and self.condition_fields
        ):
            condition_field_choices = self._build_condition_field_choices(
                self.model_name
            )
        self.condition_field_choices = condition_field_choices or {}

        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            for field_name, field in self.fields.items():
                if isinstance(field, (forms.FileField, forms.ImageField)):
                    if self.data and self.data.get(f"id_{field_name}_clear") == "true":
                        self.initial[field_name] = None
                        field.widget.attrs["data_cleared"] = "true"
                    elif self.files and field_name in self.files:
                        uploaded_file = self.files[field_name]
                        field.widget.attrs["data_uploaded_filename"] = (
                            uploaded_file.name
                        )
                        field.widget.attrs["data_cleared"] = "false"
                    else:
                        existing_file = getattr(self.instance, field_name, None)
                        if existing_file:
                            self.initial[field_name] = existing_file
                            field.widget.attrs["data_existing_filename"] = (
                                existing_file.name
                            )
                            field.widget.attrs["data_cleared"] = "false"

        if self.request and self.request.method == "POST" and self.request.FILES:
            for field_name in self.request.FILES:
                if field_name in self.fields:
                    if not self.initial.get(field_name):
                        self.initial[field_name] = self.request.FILES[field_name].name
                    field = self.fields[field_name]
                    uploaded_file = self.request.FILES[field_name]
                    field.widget.attrs["data_uploaded_filename"] = uploaded_file.name
                    field.widget.attrs["data_cleared"] = "false"

        # Add condition fields if condition_model is set OR if condition_fields are provided (for multiple instances pattern)
        if self.condition_fields:
            if self.condition_model:
                # Traditional pattern: one main model + multiple condition models
                self._add_condition_fields()
                # Set initial condition values if editing
                if (
                    hasattr(self, "instance_obj")
                    and self.instance_obj
                    and self.instance_obj.pk
                ):
                    self._set_initial_condition_values()
            else:
                # Multiple instances pattern: no condition_model, create multiple main model instances
                # Still need to add condition fields dynamically for multiple rows
                self._add_condition_fields()

        # Automatically add HTMX to ForeignKey fields with limit_choices_to that are used for condition fields
        self._add_generic_htmx_to_field()

        for field_name, field in self.fields.items():
            if getattr(field, "is_custom_field", False):
                continue
            if field_name in self.hidden_fields or isinstance(
                field.widget, forms.HiddenInput
            ):
                field.widget = forms.HiddenInput()
                field.widget.attrs.update({"class": "hidden-input"})
                continue

            existing_attrs = getattr(field.widget, "attrs", {}).copy()

            # Check if field should be readonly based on field_permissions
            is_readonly = False
            if hasattr(self, "field_permissions") and self.field_permissions:
                permission = self.field_permissions.get(field_name, "readwrite")
                is_readonly = permission == "readonly"

            # Also check if readonly was already set in attrs
            if not is_readonly:
                is_readonly = (
                    existing_attrs.get("readonly") == "readonly"
                    or existing_attrs.get("readOnly") == "readOnly"
                )

            # If readonly, check if we should skip making it readonly in create/duplicate mode for mandatory fields
            if is_readonly:
                # Check if we're in create mode or duplicate mode
                is_create_mode = not (self.instance and self.instance.pk)
                is_duplicate_mode = self.duplicate_mode

                # Check if field is mandatory (required)
                is_mandatory = False
                try:
                    model_field = self._meta.model._meta.get_field(field_name)
                    # Field is mandatory if it doesn't allow null and doesn't allow blank
                    is_mandatory = not model_field.null and not model_field.blank
                except Exception:
                    # If we can't get the model field, check form field's required attribute
                    is_mandatory = field.required

                # In create/duplicate mode, if field is mandatory, don't make it readonly
                if (is_create_mode or is_duplicate_mode) and is_mandatory:
                    is_readonly = (
                        False  # Don't make it readonly - user needs to fill it
                    )

            readonly_attrs = {}
            if is_readonly:
                readonly_attrs = {"readonly": "readonly"}

            # Apply default styling for non-checkbox fields
            if not isinstance(field.widget, forms.CheckboxInput):
                existing_placeholder = existing_attrs.get("placeholder", "")
                default_placeholder = (
                    _("Enter %(field)s") % {"field": field.label}
                    if not isinstance(field.widget, forms.Select)
                    else ""
                )

                field.widget.attrs.update(
                    {
                        "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                        "placeholder": existing_placeholder or default_placeholder,
                    }
                )

                # Restore readonly if it should be readonly
                if is_readonly:
                    field.widget.attrs.update(readonly_attrs)
                else:
                    # Remove readonly if it was set but shouldn't be
                    if "readonly" in field.widget.attrs:
                        del field.widget.attrs["readonly"]
                    if "readOnly" in field.widget.attrs:
                        del field.widget.attrs["readOnly"]

            try:
                # Try to get the field from the main model or condition model
                model_field = None
                model = self._meta.model
                try:
                    model_field = model._meta.get_field(field_name)
                except Exception:
                    if self.condition_model and field_name in self.condition_fields:
                        try:
                            model_field = self.condition_model._meta.get_field(
                                field_name
                            )
                        except Exception:
                            pass

                if model_field:
                    if isinstance(model_field, models.DateTimeField):
                        if not isinstance(field.widget, forms.HiddenInput):
                            # Check if field should be readonly
                            is_field_readonly = False
                            if (
                                hasattr(self, "field_permissions")
                                and self.field_permissions
                            ):
                                permission = self.field_permissions.get(
                                    field_name, "readwrite"
                                )
                                is_field_readonly = permission == "readonly"

                            # If readonly, check if we should skip making it readonly in create/duplicate mode for mandatory fields
                            if is_field_readonly:
                                is_create_mode = not (
                                    self.instance and self.instance.pk
                                )
                                is_duplicate_mode = self.duplicate_mode
                                is_mandatory = (
                                    not model_field.null and not model_field.blank
                                )

                                # In create/duplicate mode, if field is mandatory, don't make it readonly
                                if (
                                    is_create_mode or is_duplicate_mode
                                ) and is_mandatory:
                                    is_field_readonly = False

                            readonly_attrs = {}
                            if (
                                is_field_readonly
                                or existing_attrs.get("readonly") == "readonly"
                            ):
                                readonly_attrs = {"readonly": "readonly"}

                            field.widget = forms.DateTimeInput(
                                attrs={
                                    "type": "datetime-local",
                                    "class": (
                                        "text-color-600 p-2 placeholder:text-xs w-full "
                                        "border border-dark-50 rounded-md mt-1 "
                                        "focus-visible:outline-0 placeholder:text-dark-100 "
                                        "text-sm [transition:.3s] focus:border-primary-600"
                                    ),
                                    **existing_attrs,
                                    **readonly_attrs,  # Ensure readonly is preserved
                                },
                                format="%Y-%m-%dT%H:%M",
                            )
                            field.input_formats = ["%Y-%m-%dT%H:%M"]

                    elif isinstance(model_field, models.DateField):
                        if not isinstance(field.widget, forms.HiddenInput):
                            # Check if field should be readonly
                            is_field_readonly = False
                            if (
                                hasattr(self, "field_permissions")
                                and self.field_permissions
                            ):
                                permission = self.field_permissions.get(
                                    field_name, "readwrite"
                                )
                                is_field_readonly = permission == "readonly"

                            # If readonly, check if we should skip making it readonly in create/duplicate mode for mandatory fields
                            if is_field_readonly:
                                is_create_mode = not (
                                    self.instance and self.instance.pk
                                )
                                is_duplicate_mode = self.duplicate_mode
                                is_mandatory = (
                                    not model_field.null and not model_field.blank
                                )

                                # In create/duplicate mode, if field is mandatory, don't make it readonly
                                if (
                                    is_create_mode or is_duplicate_mode
                                ) and is_mandatory:
                                    is_field_readonly = False

                            readonly_attrs = {}
                            if (
                                is_field_readonly
                                or existing_attrs.get("readonly") == "readonly"
                            ):
                                readonly_attrs = {"readonly": "readonly"}

                            field.widget = forms.DateInput(
                                attrs={
                                    "type": "date",
                                    "class": "text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                                    **existing_attrs,
                                    **readonly_attrs,  # Ensure readonly is preserved
                                },
                                format="%Y-%m-%d",
                            )
                            field.input_formats = ["%Y-%m-%d"]

                    elif isinstance(model_field, models.TimeField):
                        if not isinstance(field.widget, forms.HiddenInput):
                            # Check if field should be readonly
                            is_field_readonly = False
                            if (
                                hasattr(self, "field_permissions")
                                and self.field_permissions
                            ):
                                permission = self.field_permissions.get(
                                    field_name, "readwrite"
                                )
                                is_field_readonly = permission == "readonly"

                            # If readonly, check if we should skip making it readonly in create/duplicate mode for mandatory fields
                            if is_field_readonly:
                                is_create_mode = not (
                                    self.instance and self.instance.pk
                                )
                                is_duplicate_mode = self.duplicate_mode
                                is_mandatory = (
                                    not model_field.null and not model_field.blank
                                )

                                # In create/duplicate mode, if field is mandatory, don't make it readonly
                                if (
                                    is_create_mode or is_duplicate_mode
                                ) and is_mandatory:
                                    is_field_readonly = False

                            readonly_attrs = {}
                            if (
                                is_field_readonly
                                or existing_attrs.get("readonly") == "readonly"
                            ):
                                readonly_attrs = {"readonly": "readonly"}

                            field.widget = forms.TimeInput(
                                attrs={
                                    "type": "time",
                                    "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm transition duration-300 focus:border-primary-600",
                                    "style": f'background-image: url("{static("assets/icons/clock_icon.svg")}"); background-repeat: no-repeat; background-position: right 12px center; background-size: 18px;',
                                    **existing_attrs,
                                    **readonly_attrs,  # Ensure readonly is preserved
                                }
                            )

                    elif isinstance(model_field, models.ManyToManyField):
                        if not isinstance(field.widget, forms.HiddenInput):
                            related_model = model_field.related_model
                            app_label = related_model._meta.app_label
                            model_name = related_model._meta.model_name

                            initial_value = []
                            if self.instance and self.instance.pk:
                                initial_value = list(
                                    getattr(self.instance, field_name).values_list(
                                        "pk", flat=True
                                    )
                                )
                            elif field_name in self.initial:
                                initial_data = self.initial[field_name]
                                if isinstance(initial_data, list):
                                    initial_value = [
                                        item.pk if hasattr(item, "pk") else item
                                        for item in initial_data
                                    ]
                                else:
                                    initial_value = [
                                        (
                                            initial_data.pk
                                            if hasattr(initial_data, "pk")
                                            else initial_data
                                        )
                                    ]

                            submitted_values = (
                                self.data.getlist(field_name, [])
                                if field_name in self.data
                                else []
                            )
                            submitted_values = [v for v in submitted_values if v]

                            all_values = list(
                                set(
                                    [v for v in (initial_value + submitted_values) if v]
                                )
                            )
                            initial_choices = []
                            if all_values:
                                selected_objects = related_model.objects.filter(
                                    pk__in=all_values
                                )
                                initial_choices = [
                                    (obj.pk, str(obj)) for obj in selected_objects
                                ]

                            # Check if field should be disabled (readonly)
                            should_disable = False
                            if (
                                hasattr(self, "field_permissions")
                                and self.field_permissions
                            ):
                                permission = self.field_permissions.get(
                                    field_name, "readwrite"
                                )
                                if permission == "readonly":
                                    # Check if we should skip disabling in create/duplicate mode for mandatory fields
                                    is_create_mode = not (
                                        self.instance and self.instance.pk
                                    )
                                    is_duplicate_mode = self.duplicate_mode
                                    is_mandatory = (
                                        not model_field.null and not model_field.blank
                                    )

                                    # Only disable if not mandatory in create/duplicate mode
                                    if not (
                                        (is_create_mode or is_duplicate_mode)
                                        and is_mandatory
                                    ):
                                        should_disable = True

                            # Get object_id if editing
                            object_id = None
                            if self.instance and self.instance.pk:
                                object_id = self.instance.pk

                            widget_attrs = {
                                "class": "select2-pagination w-full text-sm",
                                "data-url": reverse_lazy(
                                    f"horilla_generics:model_select2",
                                    kwargs={
                                        "app_label": app_label,
                                        "model_name": model_name,
                                    },
                                ),
                                "data-placeholder": _("Select %(field)s")
                                % {"field": model_field.verbose_name.title()},
                                "multiple": "multiple",
                                "data-initial": (
                                    ",".join(
                                        map(str, submitted_values or initial_value)
                                    )
                                    if (submitted_values or initial_value)
                                    else ""
                                ),
                                "data-field-name": field_name,
                                "id": f"id_{field_name}",
                                "data-form-class": f"{self.__module__}.{self.__class__.__name__}",
                                **(
                                    {"data-object-id": str(object_id)}
                                    if object_id
                                    else {}
                                ),
                                **existing_attrs,
                            }
                            if self.__class__.__name__ == "DynamicForm":
                                widget_attrs["data-parent-model"] = (
                                    f"{self._meta.model._meta.app_label}.{self._meta.model._meta.model_name}"
                                )

                            # Add disabled attribute if field is readonly
                            if should_disable:
                                widget_attrs["disabled"] = "disabled"
                                widget_attrs["data-disabled"] = "true"
                                # Add styling for disabled state
                                existing_class = widget_attrs.get("class", "")
                                widget_attrs["class"] = (
                                    f"{existing_class} bg-gray-100 cursor-not-allowed opacity-60".strip()
                                )

                            field.widget = forms.SelectMultiple(
                                choices=initial_choices, attrs=widget_attrs
                            )

                            # Also set field.disabled for Django form handling
                            if should_disable:
                                field.disabled = True

                    elif isinstance(model_field, models.ForeignKey):
                        if not isinstance(field.widget, forms.HiddenInput):
                            related_model = model_field.related_model
                            app_label = related_model._meta.app_label
                            model_name = related_model._meta.model_name

                            initial_value = None
                            if self.instance and self.instance.pk:
                                related_obj = getattr(self.instance, field_name, None)
                                initial_value = related_obj.pk if related_obj else None
                            elif field_name in self.initial:
                                initial_data = self.initial[field_name]
                                initial_value = (
                                    initial_data.pk
                                    if hasattr(initial_data, "pk")
                                    else initial_data
                                )

                            submitted_value = (
                                self.data.get(field_name)
                                if field_name in self.data
                                else None
                            )
                            all_values = [
                                v for v in [initial_value, submitted_value] if v
                            ]
                            initial_choices = []
                            try:
                                # Pre-fetch choices for initial rendering
                                queryset = related_model.objects.all()[
                                    :100
                                ]  # Limit to avoid performance issues
                                initial_choices = [
                                    (obj.pk, str(obj)) for obj in queryset
                                ]
                                if all_values:
                                    selected_objects = related_model.objects.filter(
                                        pk__in=all_values
                                    )
                                    initial_choices = [
                                        (obj.pk, str(obj)) for obj in selected_objects
                                    ] + [
                                        (obj.pk, str(obj))
                                        for obj in queryset
                                        if obj.pk not in all_values
                                    ]
                            except Exception as e:
                                logger.error(
                                    "Error fetching choices for %s: %s",
                                    field_name,
                                    str(e),
                                )

                            # Check if field should be disabled (readonly)
                            should_disable = False
                            if (
                                hasattr(self, "field_permissions")
                                and self.field_permissions
                            ):
                                permission = self.field_permissions.get(
                                    field_name, "readwrite"
                                )
                                if permission == "readonly":
                                    # Check if we should skip disabling in create/duplicate mode for mandatory fields
                                    is_create_mode = not (
                                        self.instance and self.instance.pk
                                    )
                                    is_duplicate_mode = self.duplicate_mode
                                    is_mandatory = (
                                        not model_field.null and not model_field.blank
                                    )

                                    # Only disable if not mandatory in create/duplicate mode
                                    if not (
                                        (is_create_mode or is_duplicate_mode)
                                        and is_mandatory
                                    ):
                                        should_disable = True

                            # Get object_id if editing
                            object_id = None
                            if self.instance and self.instance.pk:
                                object_id = self.instance.pk

                            widget_attrs = {
                                "class": "select2-pagination w-full",
                                "data-url": reverse_lazy(
                                    f"horilla_generics:model_select2",
                                    kwargs={
                                        "app_label": app_label,
                                        "model_name": model_name,
                                    },
                                ),
                                "data-placeholder": _("Select %(field)s")
                                % {"field": model_field.verbose_name.title()},
                                "data-initial": (
                                    str(submitted_value or initial_value)
                                    if (submitted_value or initial_value)
                                    else ""
                                ),
                                "data-field-name": field_name,
                                "id": f"id_{field_name}",
                                "data-form-class": f"{self.__module__}.{self.__class__.__name__}",
                                **(
                                    {"data-object-id": str(object_id)}
                                    if object_id
                                    else {}
                                ),
                                **existing_attrs,
                            }
                            if self.__class__.__name__ == "DynamicForm":
                                widget_attrs["data-parent-model"] = (
                                    f"{self._meta.model._meta.app_label}.{self._meta.model._meta.model_name}"
                                )

                            # Add disabled attribute if field is readonly
                            if should_disable:
                                widget_attrs["disabled"] = "disabled"
                                widget_attrs["data-disabled"] = "true"
                                # Add styling for disabled state
                                existing_class = widget_attrs.get("class", "")
                                widget_attrs["class"] = (
                                    f"{existing_class} bg-gray-100 cursor-not-allowed opacity-60".strip()
                                )

                            field.widget = forms.Select(
                                choices=[("", "---------")] + initial_choices,
                                attrs=widget_attrs,
                            )

                            # Also set field.disabled for Django form handling
                            if should_disable:
                                field.disabled = True

                    elif isinstance(field.widget, forms.Select):
                        # Check if field should be disabled (readonly)
                        should_disable = False
                        if (
                            hasattr(self, "field_permissions")
                            and self.field_permissions
                        ):
                            permission = self.field_permissions.get(
                                field_name, "readwrite"
                            )
                            if permission == "readonly":
                                # Check if we should skip disabling in create/duplicate mode for mandatory fields
                                is_create_mode = not (
                                    self.instance and self.instance.pk
                                )
                                is_duplicate_mode = self.duplicate_mode
                                try:
                                    is_mandatory = (
                                        not model_field.null and not model_field.blank
                                    )
                                except Exception:
                                    is_mandatory = field.required

                                # Only disable if not mandatory in create/duplicate mode
                                if not (
                                    (is_create_mode or is_duplicate_mode)
                                    and is_mandatory
                                ):
                                    should_disable = True

                        field.widget.attrs.update(
                            {"class": "js-example-basic-single headselect"}
                        )

                        # Add disabled attribute if field is readonly
                        if should_disable:
                            field.widget.attrs["disabled"] = "disabled"
                            field.widget.attrs["data-disabled"] = "true"
                            # Add styling for disabled state
                            existing_class = field.widget.attrs.get("class", "")
                            field.widget.attrs["class"] = (
                                f"{existing_class} bg-gray-100 cursor-not-allowed opacity-60".strip()
                            )
                            field.disabled = True

            except Exception as e:
                logger.error("Error processing field %s: %s", field_name, str(e))

            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({"class": "sr-only peer"})
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs.update(
                    {
                        "rows": 4,
                        "placeholder": _("Enter %(field)s here...")
                        % {"field": field.label},
                    }
                )

        # Apply field permissions: remove hidden fields and readonly fields in create/duplicate mode
        # Do this AFTER all widget processing is complete
        if self.field_permissions:
            # Check if we're in create mode or duplicate mode
            is_create_mode = not (self.instance and self.instance.pk)
            is_duplicate_mode = self.duplicate_mode

            fields_to_remove = []
            for field_name, field in list(self.fields.items()):
                # Skip condition fields and already hidden fields
                if (
                    field_name in self.condition_fields
                    or field_name in self.hidden_fields
                ):
                    continue

                permission = self.field_permissions.get(field_name, "readwrite")

                # Remove hidden fields
                if permission == "hidden":
                    # In create/duplicate mode, don't hide mandatory fields (user needs to fill them)
                    if is_create_mode or is_duplicate_mode:
                        # Check if field is mandatory (required)
                        is_mandatory = False
                        try:
                            model_field = self._meta.model._meta.get_field(field_name)
                            # Field is mandatory if it doesn't allow null and doesn't allow blank
                            is_mandatory = (
                                not model_field.null and not model_field.blank
                            )
                        except Exception:
                            # If we can't get the model field, check form field's required attribute
                            is_mandatory = field.required

                        # Only hide if NOT mandatory in create/duplicate mode
                        if not is_mandatory:
                            fields_to_remove.append(field_name)
                    else:
                        # In edit mode, always hide fields with "hidden" permission
                        fields_to_remove.append(field_name)
                # In create mode or duplicate mode, hide readonly fields ONLY if they are NOT mandatory
                elif permission == "readonly" and (is_create_mode or is_duplicate_mode):
                    # Check if field is mandatory (required)
                    is_mandatory = False
                    try:
                        model_field = self._meta.model._meta.get_field(field_name)
                        # Field is mandatory if it doesn't allow null and doesn't allow blank
                        is_mandatory = not model_field.null and not model_field.blank
                    except Exception:
                        # If we can't get the model field, check form field's required attribute
                        is_mandatory = field.required

                    # Only hide readonly fields if they are NOT mandatory
                    # Mandatory readonly fields should be shown in create/duplicate mode (editable)
                    if not is_mandatory:
                        fields_to_remove.append(field_name)

            # Remove fields
            for field_name in fields_to_remove:
                if field_name in self.fields:
                    del self.fields[field_name]

    def _add_condition_fields(self):
        """Add condition fields dynamically from the condition model (or main model if no condition_model) with HTMX support"""
        row_id = getattr(self, "row_id", "0")
        model_name = getattr(self, "model_name", "")

        # Determine which model to use for field definitions
        # If condition_model exists, use it; otherwise use the main model (for multiple instances pattern)
        model_for_fields = (
            self.condition_model if self.condition_model else self.Meta.model
        )

        for field_name in self.condition_fields:
            try:
                model_field = model_for_fields._meta.get_field(field_name)
                # If still not found, use generic endpoint for field choices

                # Handle "field" field with dynamic choices from condition_field_choices
                if field_name == "field" and field_name in self.condition_field_choices:
                    # Get existing condition data for this row if editing
                    existing_field = ""
                    existing_value = ""
                    # First check if passed via initial (from add_condition_row)
                    if hasattr(self, "initial") and isinstance(self.initial, dict):
                        existing_field = self.initial.get("_existing_field", "")
                        existing_value = self.initial.get("_existing_value", "")
                    # Fallback to checking instance_obj for row 0
                    if (
                        not existing_field
                        and hasattr(self, "instance_obj")
                        and self.instance_obj
                        and self.instance_obj.pk
                    ):
                        related_name = getattr(
                            self, "condition_related_name", "conditions"
                        )
                        if not hasattr(self.instance_obj, related_name):
                            for name in ["conditions", "criteria"]:
                                if hasattr(self.instance_obj, name):
                                    related_name = name
                                    break
                        if hasattr(self.instance_obj, related_name):
                            existing_conditions = getattr(
                                self.instance_obj, related_name
                            ).all()
                            if existing_conditions.exists():
                                try:
                                    row_index = int(row_id) if row_id.isdigit() else 0
                                    conditions_list = list(existing_conditions)
                                    if 0 <= row_index < len(conditions_list):
                                        condition = conditions_list[row_index]
                                        existing_field = (
                                            getattr(condition, "field", "") or ""
                                        )
                                        existing_value = (
                                            getattr(condition, "value", "") or ""
                                        )
                                except (ValueError, IndexError):
                                    # Fallback to first condition for row 0
                                    if row_id == "0":
                                        first_condition = existing_conditions.first()
                                        existing_field = (
                                            getattr(first_condition, "field", "") or ""
                                        )
                                        existing_value = (
                                            getattr(first_condition, "value", "") or ""
                                        )

                    # Build hx-vals - include existing field and value so it shows on page load
                    hx_vals_parts = [
                        f'"model_name": "{model_name}"',
                        f'"row_id": "{row_id}"',
                    ]
                    condition_model = getattr(self, "condition_model", None)
                    if condition_model:
                        hx_vals_parts.append(
                            f'"condition_model": "{condition_model._meta.app_label}.{condition_model._meta.model_name}"'
                        )
                    if existing_field:
                        hx_vals_parts.append(
                            f'"field_{row_id}": "{escape(str(existing_field))}"'
                        )
                    if existing_value:
                        existing_value_escaped = escape(str(existing_value))
                        hx_vals_parts.append(
                            f'"value_{row_id}": "{existing_value_escaped}"'
                        )
                    hx_vals = "{" + ", ".join(hx_vals_parts) + "}"

                    hx_include = f'[name="field_{row_id}"],[name="operator_{row_id}"]'
                    if (
                        hasattr(self, "condition_hx_include")
                        and self.condition_hx_include
                    ):
                        hx_include += f",{self.condition_hx_include}"

                    form_field = forms.ChoiceField(
                        choices=self.condition_field_choices[field_name],
                        required=False,
                        label=model_field.verbose_name
                        or field_name.replace("_", " ").title(),
                        widget=forms.Select(
                            attrs={
                                "class": "js-example-basic-single headselect",
                                "data-placeholder": f'Select {field_name.replace("_", " ").title()}',
                                "id": f"id_{field_name}_{row_id}",
                                "name": f"{field_name}_{row_id}",
                                "hx-get": reverse_lazy(
                                    "horilla_generics:get_field_value_widget"
                                ),
                                "hx-target": f"#id_value_{row_id}_container",
                                "hx-swap": "innerHTML",
                                "hx-vals": hx_vals,
                                "hx-include": hx_include,
                                "hx-trigger": "change,load",
                            }
                        ),
                    )
                    # Set initial value if editing
                    if existing_field:
                        form_field.initial = existing_field
                    self.fields[field_name] = form_field
                # Handle "value" field - will be dynamically generated by get_field_value_widget
                elif field_name == "value":
                    # Value field will be dynamically generated, don't add it here
                    pass
                # Handle fields with choices from condition_field_choices (e.g., operator, logical_operator)
                elif field_name in self.condition_field_choices:
                    form_field = forms.ChoiceField(
                        choices=self.condition_field_choices[field_name],
                        required=False,
                        label=model_field.verbose_name
                        or field_name.replace("_", " ").title(),
                        widget=forms.Select(
                            attrs={
                                "class": "js-example-basic-single headselect",
                                "data-placeholder": f'Select {field_name.replace("_", " ").title()}',
                                "id": f"id_{field_name}_{row_id}",
                                "name": f"{field_name}_{row_id}",
                            }
                        ),
                    )
                    self.fields[field_name] = form_field
                elif hasattr(model_field, "choices") and model_field.choices:
                    form_field = forms.ChoiceField(
                        choices=[("", "---------")] + list(model_field.choices),
                        required=False,
                        label=model_field.verbose_name
                        or field_name.replace("_", " ").title(),
                        widget=forms.Select(
                            attrs={
                                "class": "js-example-basic-single headselect",
                                "data-placeholder": _("Select %(field)s")
                                % {"field": field_name.replace("_", " ").title()},
                                "id": f"id_{field_name}_{row_id}",
                                "name": f"{field_name}_{row_id}",
                            }
                        ),
                    )
                    form_field.is_custom_field = True
                    self.fields[field_name] = form_field
                elif isinstance(model_field, models.ForeignKey):
                    related_model = model_field.related_model
                    app_label = related_model._meta.app_label
                    model_name_fk = related_model._meta.model_name

                    initial_choices = []
                    try:
                        # Pre-fetch a limited set of choices for initial rendering
                        queryset = related_model.objects.all()[
                            :100
                        ]  # Limit to avoid performance issues
                        initial_choices = [(obj.pk, str(obj)) for obj in queryset]
                    except Exception as e:
                        logger.error(
                            "Error fetching choices for condition field %s: %s",
                            field_name,
                            str(e),
                        )

                    form_field = forms.ChoiceField(
                        choices=[("", "---------")] + initial_choices,
                        required=False,
                        label=model_field.verbose_name
                        or field_name.replace("_", " ").title(),
                        widget=forms.Select(
                            attrs={
                                "class": "select2-pagination w-full",
                                "data-url": reverse_lazy(
                                    f"horilla_generics:model_select2",
                                    kwargs={
                                        "app_label": app_label,
                                        "model_name": model_name_fk,
                                    },
                                ),
                                "data-placeholder": _("Select %(field)s")
                                % {"field": model_field.verbose_name.title()},
                                "data-field-name": field_name,
                                "id": f"id_{field_name}_{row_id}",
                                "name": f"{field_name}_{row_id}",
                                "data-form-class": f"{self.__module__}.{self.__class__.__name__}",
                            }
                        ),
                    )
                    form_field.is_custom_field = True
                    self.fields[field_name] = form_field
                elif isinstance(model_field, models.CharField):
                    form_field = forms.CharField(
                        max_length=model_field.max_length,
                        required=False,
                        label=model_field.verbose_name
                        or field_name.replace("_", " ").title(),
                        widget=forms.TextInput(
                            attrs={
                                "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md  focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                                "placeholder": _("Enter %(field)s")
                                % {"field": field_name.replace("_", " ").title()},
                                "id": f"id_{field_name}_{row_id}",
                                "name": f"{field_name}_{row_id}",
                            }
                        ),
                    )
                    form_field.is_custom_field = True
                    self.fields[field_name] = form_field
                elif isinstance(model_field, models.IntegerField):
                    form_field = forms.IntegerField(
                        required=False,
                        label=model_field.verbose_name
                        or field_name.replace("_", " ").title(),
                        widget=forms.NumberInput(
                            attrs={
                                "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md  focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                                "placeholder": _("Enter %(field)s")
                                % {"field": field_name.replace("_", " ").title()},
                                "id": f"id_{field_name}_{row_id}",
                                "name": f"{field_name}_{row_id}",
                            }
                        ),
                    )
                    form_field.is_custom_field = True
                    self.fields[field_name] = form_field
                elif isinstance(model_field, models.BooleanField):
                    form_field = forms.BooleanField(
                        required=False,
                        label=model_field.verbose_name
                        or field_name.replace("_", " ").title(),
                        widget=forms.CheckboxInput(
                            attrs={
                                "class": "sr-only peer",
                                "id": f"id_{field_name}_{row_id}",
                                "name": f"{field_name}_{row_id}",
                            }
                        ),
                    )
                    form_field.is_custom_field = True
                    self.fields[field_name] = form_field
                else:
                    form_field = forms.CharField(
                        required=False,
                        label=model_field.verbose_name
                        or field_name.replace("_", " ").title(),
                        widget=forms.TextInput(
                            attrs={
                                "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md  focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                                "placeholder": _("Enter %(field)s")
                                % {"field": field_name.replace("_", " ").title()},
                                "id": f"id_{field_name}_{row_id}",
                                "name": f"{field_name}_{row_id}",
                            }
                        ),
                    )
                    form_field.is_custom_field = True
                    self.fields[field_name] = form_field

            except Exception as e:
                logger.error("Error adding condition field %s: %s", field_name, str(e))

    def _add_generic_htmx_to_field(self):
        """
        Automatically add HTMX attributes to ForeignKey fields with limit_choices_to
        that are used as content_type_field for condition fields.
        Works generically regardless of field name (model, content_type, module, etc.)

        """
        # Only add HTMX if condition_fields exist
        if not self.condition_fields:
            return

        # Get content_type_field name from view (passed via kwargs or request)
        content_type_field_name = None
        if hasattr(self, "request") and self.request:
            # Try to get from view attribute (set in HorillaSingleFormView)
            view = getattr(self.request, "resolver_match", None)
            if view and view.func:
                view_instance = getattr(view.func, "view_class", None)
                if view_instance:
                    content_type_field_name = getattr(
                        view_instance, "content_type_field", None
                    )

        # If not found, try to detect automatically by finding ForeignKey with limit_choices_to
        if not content_type_field_name:
            for field_name, field in self.fields.items():
                if isinstance(field, forms.ModelChoiceField):
                    try:
                        model_field = self._meta.model._meta.get_field(field_name)
                        if isinstance(model_field, models.ForeignKey):
                            # Check if it has limit_choices_to
                            if model_field.remote_field.limit_choices_to:
                                # Check if it's a ForeignKey to HorillaContentType
                                related_model = model_field.related_model
                                if (
                                    related_model
                                    and related_model.__name__ == "HorillaContentType"
                                ):
                                    content_type_field_name = field_name
                                    break
                    except (models.FieldDoesNotExist, AttributeError):
                        continue

        # If we found a content_type_field, add HTMX to it
        if content_type_field_name and content_type_field_name in self.fields:
            row_id = getattr(self, "row_id", "0")
            field = self.fields[content_type_field_name]

            # Check if HTMX is already added (don't override custom HTMX)
            if "hx-get" in field.widget.attrs:
                return

            # Get HTMX URL - try form class attribute first, then auto-detect
            hx_get_url = None
            if hasattr(self.__class__, "htmx_field_choices_url"):
                try:
                    hx_get_url = reverse_lazy(self.__class__.htmx_field_choices_url)
                    # Test if the URL can be resolved by trying to convert to string
                    str(hx_get_url)
                except Exception:
                    hx_get_url = None

            # Helper function to safely check if a URL pattern exists
            def try_reverse(pattern):
                try:
                    url = reverse_lazy(pattern)
                    str(url)  # Force evaluation to check if it's valid
                    return url
                except Exception:
                    return None

            # If not set, try to auto-detect based on app_label and common patterns
            if hx_get_url is None:
                app_label = self._meta.model._meta.app_label
                model_name = self._meta.model._meta.model_name.lower()

                # Try common URL patterns
                url_patterns = [
                    f"{app_label}:{model_name}_field_choices_view",
                    f"{app_label}:{content_type_field_name}_field_choices_view",
                    f"{app_label}:get_{model_name}_field_choices",
                ]

                for pattern in url_patterns:
                    hx_get_url = try_reverse(pattern)
                    if hx_get_url:
                        break

            if hx_get_url is None:
                hx_get_url = reverse_lazy("horilla_generics:get_model_field_choices")

            # Determine target - usually the first condition field container
            first_condition_field = (
                self.condition_fields[0] if self.condition_fields else "field"
            )
            hx_target = f"#id_{first_condition_field}_{row_id}_container"

            # Build hx-vals - include row_id, field_name_pattern, and any instance ID if available
            # Note: content_type/model value comes from hx-include, so we don't need it in hx-vals
            field_name_pattern = f"{first_condition_field}_{{row_id}}"

            hx_vals_parts = [
                f'"row_id": "{row_id}"',
                f'"field_name_pattern": "{field_name_pattern}"',
            ]

            # Add filtering parameters if form class specifies them
            if hasattr(self.__class__, "htmx_field_filter"):
                filter_config = self.__class__.htmx_field_filter
                if filter_config.get("only_text_fields"):
                    hx_vals_parts.append('"only_text_fields": "true"')
                if filter_config.get("exclude_choice_fields"):
                    hx_vals_parts.append('"exclude_choice_fields": "true"')
                if filter_config.get("field_types"):
                    field_types_str = ",".join(filter_config["field_types"])
                    hx_vals_parts.append(f'"field_types": "{field_types_str}"')

            # Add instance ID if available (for forms like HorillaAutomationForm)
            if (
                hasattr(self, "instance_obj")
                and self.instance_obj
                and self.instance_obj.pk
            ):
                # Try model-specific ID name first (e.g., automation_id for HorillaAutomation)
                model_name_lower = self._meta.model._meta.model_name.lower()
                # Convert "HorillaAutomation" -> "automation_id", "MatchingRule" -> "matching_rule_id"
                if model_name_lower.startswith("horilla"):
                    instance_id_name = f"{model_name_lower.replace('horilla', '')}_id"
                else:
                    instance_id_name = f"{model_name_lower}_id"
                hx_vals_parts.append(f'"{instance_id_name}": "{self.instance_obj.pk}"')

            hx_vals = "{" + ", ".join(hx_vals_parts) + "}"

            # Build hx-include - use field name in quotes for consistency
            hx_include = f'[name="{content_type_field_name}"]'
            if hasattr(self, "condition_hx_include") and self.condition_hx_include:
                hx_include += f",{self.condition_hx_include}"

            # Add HTMX attributes (only if not already set)
            if "hx-get" not in field.widget.attrs:
                field.widget.attrs.update(
                    {
                        "hx-get": hx_get_url,
                        "hx-target": hx_target,
                        "hx-swap": "innerHTML",
                        "hx-include": hx_include,
                        "hx-vals": hx_vals,
                        "hx-trigger": "change",
                    }
                )

    def _get_model_name_from_request_or_instance(self, kwargs):
        """Generic method to extract model_name from request or instance"""
        model_name = None
        request = kwargs.get("request") or self.request
        instance_obj = kwargs.get("instance") or self.instance_obj

        if request:
            # Try to get from initial first (passed from view)
            if "initial" in kwargs and "model_name" in kwargs["initial"]:
                model_name = kwargs["initial"]["model_name"]
            else:
                model_name = (
                    request.GET.get("model_name")
                    or request.POST.get("model_name")
                    or request.GET.get("model")
                    or (request.POST.get("model") if hasattr(request, "POST") else None)
                )

                # If model_id is provided, convert to model name (for HorillaContentType)
                if model_name and model_name.isdigit():
                    try:
                        from horilla_core.models import HorillaContentType

                        content_type = HorillaContentType.objects.get(pk=model_name)
                        model_name = content_type.model
                    except Exception:
                        model_name = None

        # Try to get from instance (common patterns: instance.model.model, instance.rule.module, etc.)
        if not model_name and instance_obj and instance_obj.pk:
            # Check common patterns
            if hasattr(instance_obj, "model") and hasattr(instance_obj.model, "model"):
                model_name = instance_obj.model.model
            elif hasattr(instance_obj, "rule") and hasattr(instance_obj.rule, "module"):
                model_name = instance_obj.rule.module
            elif hasattr(instance_obj, "module"):
                module = getattr(instance_obj, "module", None)
                # Handle HorillaContentType ForeignKey (e.g., DashboardComponent.module)
                if module and hasattr(module, "model"):
                    model_name = module.model
                # Handle direct string/CharField
                elif isinstance(module, str):
                    model_name = module

        return model_name

    def _build_condition_field_choices(self, model_name=None):
        """Build condition_field_choices automatically from condition_model"""
        if not self.condition_model or not self.condition_fields:
            return {}

        condition_field_choices = {}

        for field_name in self.condition_fields:
            if field_name == "field":
                # Field choices come from the target model
                condition_field_choices["field"] = (
                    self._get_model_field_choices(model_name)
                    if model_name
                    else [("", "---------")]
                )
            else:
                # Other fields (operator, logical_operator, etc.) get choices from condition model
                condition_field_choices[field_name] = (
                    self._get_condition_field_choices_from_model(
                        field_name, self.condition_model
                    )
                )

        return condition_field_choices

    def _get_condition_field_choices_from_model(self, field_name, condition_model=None):
        """Get choices for a condition field from the condition model's field definition"""
        # Get condition_model from self or parameter
        if not condition_model:
            condition_model = getattr(self, "condition_model", None)

        if not condition_model:
            return [("", "---------")]

        try:
            model_field = condition_model._meta.get_field(field_name)
            if hasattr(model_field, "choices") and model_field.choices:
                # Return choices from model field, with empty option prepended
                return [("", "---------")] + list(model_field.choices)
        except (AttributeError, Exception):
            pass

        return [("", "---------")]

    def _get_model_field_choices(self, model_name):
        """Generic method to get field choices for a model (excluding reverse relations)"""
        field_choices = [("", "---------")]

        if not model_name:
            return field_choices

        try:
            model = None
            for app_config in apps.get_app_configs():
                try:
                    model = apps.get_model(
                        app_label=app_config.label, model_name=model_name.lower()
                    )
                    break
                except (LookupError, ValueError):
                    continue

            if model:
                # Use _meta.fields and _meta.many_to_many to get only forward fields
                # This excludes one-to-many and many-to-many reverse relationships
                # which don't have a direct 'name' attribute and are accessed via related_name
                all_forward_fields = list(model._meta.fields) + list(
                    model._meta.many_to_many
                )

                for field in all_forward_fields:
                    # Skip excluded fields
                    if field.name in [
                        "id",
                        "pk",
                        "created_at",
                        "updated_at",
                        "created_by",
                        "updated_by",
                        "company",
                        "additional_info",
                    ]:
                        continue
                    # Skip non-editable fields (e.g. editable=False on the model)
                    if not getattr(field, "editable", True):
                        continue

                    verbose_name = (
                        getattr(field, "verbose_name", None)
                        or field.name.replace("_", " ").title()
                    )
                    field_choices.append((field.name, verbose_name))
        except Exception as e:
            logger.error(
                "Error fetching model %s: %s", model_name, str(e), exc_info=True
            )

        return field_choices

    def _set_initial_condition_values(self):
        """Generic method to set initial values for condition fields in edit mode"""
        if not (
            hasattr(self, "instance_obj") and self.instance_obj and self.instance_obj.pk
        ):
            return

        if not (hasattr(self, "condition_fields") and self.condition_fields):
            return

        # Get related manager name (defaults to "conditions")
        related_name = getattr(self, "condition_related_name", "conditions")
        if not hasattr(self.instance_obj, related_name):
            # Try common names
            for name in ["conditions", "criteria", "team_members"]:
                if hasattr(self.instance_obj, name):
                    related_name = name
                    break
            else:
                return

        existing_conditions = getattr(self.instance_obj, related_name).all()
        if hasattr(self, "row_id") and self.row_id != "0":
            return

        if existing_conditions.exists():
            first_condition = existing_conditions.first()
            for field_name in self.condition_fields:
                if field_name in self.fields:
                    value = getattr(first_condition, field_name, "")
                    self.fields[field_name].initial = value
                    field_key_0 = f"{field_name}_0"
                    if field_key_0 in self.fields:
                        self.fields[field_key_0].initial = value

    def _extract_condition_rows(self):
        """Generic method to extract condition rows from form data"""
        condition_rows = []

        if not (hasattr(self, "condition_fields") and self.condition_fields):
            return condition_rows

        if not self.data:
            return condition_rows

        row_ids = set()

        # Find all row IDs from form data keys (e.g., field_0, operator_1, value_2)
        for key in self.data.keys():
            for field_name in self.condition_fields:
                if key.startswith(f"{field_name}_"):
                    row_id = key.replace(f"{field_name}_", "")
                    if row_id.isdigit():
                        row_ids.add(row_id)

        # Also check for row 0 fields (without suffix or with _0 suffix)
        if any(f in self.data for f in self.condition_fields) or any(
            f"{f}_0" in self.data for f in self.condition_fields
        ):
            row_ids.add("0")

        # Extract data for each row
        for row_id in sorted(row_ids, key=lambda x: int(x)):
            row_data = {}
            has_required_data = True

            for field_name in self.condition_fields:
                # Handle row 0: try _0 suffix first, then field name without suffix
                if row_id == "0":
                    field_key = (
                        f"{field_name}_0"
                        if f"{field_name}_0" in self.data
                        else field_name
                    )
                else:
                    field_key = f"{field_name}_{row_id}"

                value = self.data.get(field_key, "").strip()
                row_data[field_name] = value

                # Check if required fields are present (field and operator are typically required)
                if field_name in ["field", "operator"] and not value:
                    has_required_data = False

            # Only add row if it has required data
            if has_required_data and row_data.get("field") and row_data.get("operator"):
                # Use "order" or "sequence" based on what the model expects
                row_data["order"] = int(row_id)
                condition_rows.append(row_data)

        return condition_rows

    def clean(self):
        cleaned_data = super().clean()

        if self.condition_fields and not self.condition_model:
            for field_name in self.condition_fields:
                if field_name in cleaned_data:
                    del cleaned_data[field_name]

        for field_name, field in self.fields.items():
            if field_name not in cleaned_data:
                continue

            value = cleaned_data[field_name]
            if not value:
                continue

            # Skip condition fields (handled separately)
            if self.condition_fields and field_name in self.condition_fields:
                continue

            try:
                model = self._meta.model
                try:
                    model_field = model._meta.get_field(field_name)
                except Exception:
                    continue

                # Validate ModelChoiceField (ForeignKey)
                if isinstance(field, forms.ModelChoiceField) and isinstance(
                    model_field, models.ForeignKey
                ):
                    # Get FRESH filtered queryset
                    fresh_queryset = self._get_fresh_queryset(
                        field_name, model_field.related_model
                    )
                    if (
                        fresh_queryset is not None
                        and not fresh_queryset.filter(pk=value.pk).exists()
                    ):
                        self.add_error(
                            field_name,
                            "Invalid selection. You don't have permission to select this option.",
                        )

                # Validate ModelMultipleChoiceField (ManyToMany)
                elif isinstance(field, forms.ModelMultipleChoiceField) and isinstance(
                    model_field, models.ManyToManyField
                ):
                    # Get FRESH filtered queryset
                    fresh_queryset = self._get_fresh_queryset(
                        field_name, model_field.related_model
                    )
                    if fresh_queryset is not None:
                        submitted_pks = set([obj.pk for obj in value])
                        valid_pks = set(fresh_queryset.values_list("pk", flat=True))
                        if not submitted_pks.issubset(valid_pks):
                            self.add_error(
                                field_name,
                                "Invalid selection. You don't have permission to select some options.",
                            )

                # Validate ChoiceField (for fields with choices)
                elif isinstance(field, forms.ChoiceField) and not isinstance(
                    field, forms.ModelChoiceField
                ):
                    if hasattr(field, "choices") and field.choices:
                        valid_choices = [choice[0] for choice in field.choices]
                        if value not in valid_choices:
                            self.add_error(
                                field_name,
                                "Invalid choice. Please select a valid option.",
                            )

            except Exception as e:
                logger.error("Error validating field %s: %s", field_name, str(e))

        if hasattr(self, "field_permissions") and self.field_permissions:
            # Only validate in edit mode (when instance exists)
            if self.instance and self.instance.pk:
                for field_name, permission in self.field_permissions.items():
                    if permission == "readonly" and field_name in self.fields:
                        # Get the model field to determine the type
                        try:
                            model_field = self._meta.model._meta.get_field(field_name)
                        except Exception:
                            # Field might not exist in model (could be a property)
                            continue

                        # Get original value from instance
                        if isinstance(model_field, models.ManyToManyField):
                            # ManyToMany field
                            original_value = list(
                                getattr(self.instance, field_name).all()
                            )
                        elif isinstance(model_field, models.ForeignKey):
                            # ForeignKey field
                            original_value = getattr(self.instance, field_name, None)
                        else:
                            # Regular field (CharField, IntegerField, etc.)
                            original_value = getattr(self.instance, field_name, None)

                        # Check if the value was changed
                        submitted_value = cleaned_data.get(field_name)
                        value_changed = False

                        if isinstance(model_field, models.ManyToManyField):
                            # Compare ManyToMany by comparing lists of PKs
                            original_pks = (
                                set([obj.pk for obj in original_value])
                                if original_value
                                else set()
                            )
                            submitted_pks = (
                                set([obj.pk for obj in submitted_value])
                                if submitted_value
                                else set()
                            )
                            value_changed = original_pks != submitted_pks
                        elif isinstance(model_field, models.ForeignKey):
                            # Compare ForeignKey by comparing PKs
                            original_pk = original_value.pk if original_value else None
                            submitted_pk = (
                                submitted_value.pk if submitted_value else None
                            )
                            value_changed = original_pk != submitted_pk
                        else:
                            # Compare regular fields
                            value_changed = original_value != submitted_value

                        # If value was changed, restore original and add validation error
                        if value_changed:
                            cleaned_data[field_name] = original_value
                            self.add_error(
                                field_name,
                                forms.ValidationError(
                                    _(
                                        "This field is read-only and cannot be modified."
                                    ),
                                    code="readonly_field",
                                ),
                            )
                        else:
                            # Ensure original value is set even if not changed
                            cleaned_data[field_name] = original_value

        # Validate condition fields
        if self.condition_fields and self.condition_model:
            for field_name in self.condition_fields:
                if field_name not in cleaned_data or not cleaned_data[field_name]:
                    continue

                try:
                    value = cleaned_data[field_name]
                    field = self.fields.get(field_name)
                    model_field = self.condition_model._meta.get_field(field_name)

                    if not field:
                        continue

                    # Validate ModelChoiceField in condition fields
                    if isinstance(field, forms.ModelChoiceField) and isinstance(
                        model_field, models.ForeignKey
                    ):
                        fresh_queryset = self._get_fresh_queryset(
                            field_name, model_field.related_model
                        )
                        if fresh_queryset is not None:
                            pk_to_check = value.pk if hasattr(value, "pk") else value
                            if not fresh_queryset.filter(pk=pk_to_check).exists():
                                self.add_error(
                                    field_name,
                                    "Select a valid choice. That choice is not one of the available choices.",
                                )

                    # Validate ChoiceField in condition fields
                    elif isinstance(field, forms.ChoiceField) and not isinstance(
                        field, forms.ModelChoiceField
                    ):
                        if hasattr(field, "choices") and field.choices:
                            valid_choices = [choice[0] for choice in field.choices]
                            if value not in valid_choices:
                                self.add_error(
                                    field_name,
                                    "Select a valid choice. That choice is not one of the available choices.",
                                )

                except Exception as e:
                    logger.error(
                        "Error validating condition field %s: %s", field_name, str(e)
                    )

        return cleaned_data

    def _get_fresh_queryset(self, field_name, related_model):
        """
        Get a FRESH filtered queryset by re-applying owner filtration logic.
        """
        if not self.request or not self.request.user:
            return None

        try:

            user = self.request.user

            # Start with all objects
            queryset = related_model.objects.all()

            # Apply owner filtration (same as Select2 view)
            if related_model is User:
                allowed_user_ids = self._get_allowed_user_ids(user)
                queryset = queryset.filter(id__in=allowed_user_ids)
            elif hasattr(related_model, "OWNER_FIELDS") and related_model.OWNER_FIELDS:
                allowed_user_ids = self._get_allowed_user_ids(user)
                if allowed_user_ids:
                    query = Q()
                    for owner_field in related_model.OWNER_FIELDS:
                        query |= Q(**{f"{owner_field}__id__in": allowed_user_ids})
                    queryset = queryset.filter(query)
                else:
                    queryset = queryset.none()

            return queryset

        except Exception as e:
            logger.error("Error getting fresh queryset for %s: %s", field_name, str(e))
            return related_model.objects.all()

    def _get_allowed_user_ids(self, user):
        """Get list of allowed user IDs (self + subordinates)"""

        if not user or not user.is_authenticated:
            return []

        if user.is_superuser:
            return list(User.objects.values_list("id", flat=True))

        user_role = getattr(user, "role", None)
        if not user_role:
            return [user.id]

        def get_subordinate_roles(role):
            sub_roles = role.subroles.all()
            all_sub_roles = []
            for sub_role in sub_roles:
                all_sub_roles.append(sub_role)
                all_sub_roles.extend(get_subordinate_roles(sub_role))
            return all_sub_roles

        subordinate_roles = get_subordinate_roles(user_role)
        subordinate_users = User.objects.filter(role__in=subordinate_roles).distinct()

        allowed_user_ids = [user.id] + list(
            subordinate_users.values_list("id", flat=True)
        )
        return allowed_user_ids


class HorillaHistoryForm(forms.Form):
    """Base form for filtering history by date using calendar picker"""

    filter_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                "placeholder": "Select date to filter",
            }
        ),
    )

    def apply_filter(self, history_by_date):
        """Apply the selected date filter to a sequence of (date, entries) pairs.

        If the form is invalid or no date is selected, the original sequence is returned.
        """
        if not self.is_valid():
            return history_by_date

        filter_date = self.cleaned_data.get("filter_date")
        if filter_date:
            return [
                (date, entries)
                for date, entries in history_by_date
                if date == filter_date
            ]
        return history_by_date


class RowFieldWidget(forms.MultiWidget):
    """Multi-widget for rendering multiple fields in a single row layout."""

    template_name = "forms/widgets/row_field_widget.html"

    def __init__(self, field_configs, attrs=None):
        widgets = []
        self.field_configs = field_configs
        for config in field_configs:
            if config["type"] == "select":
                widgets.append(
                    forms.Select(
                        attrs={
                            "class": "normal-seclect headselect",
                            "choices": config.get("choices", []),
                        }
                    )
                )
            elif config["type"] == "text":
                widgets.append(
                    forms.TextInput(
                        attrs={
                            "class": "h-[35px] text-color-600 p-2 placeholder:text-xs w-full border border-dark-50 rounded-md focus-visible:outline-0 placeholder:text-dark-100 text-sm transition focus:border-primary-600",
                            "placeholder": config.get("placeholder", "Enter Value"),
                        }
                    )
                )
        super().__init__(widgets, attrs)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["field_configs"] = self.field_configs
        return context


class RowField(forms.MultiValueField):
    """Multi-value field for handling multiple related fields in a row layout."""

    widget = RowFieldWidget

    def __init__(self, field_configs, *args, **kwargs):
        fields = []
        self.field_configs = field_configs
        for config in field_configs:
            if config["type"] == "select":
                fields.append(
                    forms.ChoiceField(
                        choices=config.get("choices", []),
                        required=config.get("required", True),
                    )
                )
            elif config["type"] == "text":
                fields.append(
                    forms.CharField(
                        required=config.get("required", True),
                        max_length=config.get("max_length", None),
                    )
                )
        super().__init__(fields, *args, **kwargs)
        self.is_row_field = True

    def compress(self, data_list):
        # Process the data into your desired format
        return data_list


class CustomFileInput(forms.ClearableFileInput):
    """Custom file input widget with enhanced display and preview capabilities."""

    template_name = "forms/widgets/custom_file_input.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)

        selected_filename = None
        if value:
            # Check if it's a FieldFile object
            if hasattr(value, "name") and value.name:
                # Extract just the filename from the full path
                selected_filename = value.name.split("/")[-1]
            elif isinstance(value, str):
                selected_filename = value.split("/")[-1]

        context["selected_filename"] = selected_filename
        return context


class HorillaAttachmentForm(forms.ModelForm):
    """Form for creating and editing attachments with title, file, and description."""

    class Meta:
        """Meta options for HorillaAttachmentForm."""

        model = HorillaAttachment
        fields = ["title", "file", "description"]
        labels = {
            "file": "",  # hide label
        }
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                    "placeholder": "Enter title",
                }
            ),
            "file": CustomFileInput(
                attrs={
                    "class": "hidden",
                    "id": "attachmentUpload",
                }
            ),
            "description": SummernoteInplaceWidget(
                attrs={
                    "summernote": {
                        "width": "100%",
                        "height": "300px",
                        "airMode": False,
                        "styleTags": [
                            "p",
                            "blockquote",
                            "pre",
                            "h1",
                            "h2",
                            "h3",
                            "h4",
                            "h5",
                            "h6",
                            {
                                "title": "Bold",
                                "tag": "b",
                                "className": "font-bold",
                                "value": "b",
                            },
                            {
                                "title": "Italic",
                                "tag": "i",
                                "className": "italic",
                                "value": "i",
                            },
                        ],
                    }
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # If editing (instance exists), escape the description content
        if self.instance and self.instance.pk and self.instance.description:
            # Replace HTML entities with double-escaped versions
            escaped_description = self.instance.description.replace(
                "&lt;", "&amp;lt;"
            ).replace("&gt;", "&amp;gt;")
            self.initial["description"] = escaped_description
