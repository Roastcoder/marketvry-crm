"""
Forms module for Activity-related operations including Meetings,
Calls, Events, and general Activity creation.
"""

# Third-party imports (Django)
from collections import OrderedDict

from django import forms
from django.db.models import Q
from django.forms import ValidationError

from horilla.auth.models import User

# First-party / Horilla imports
from horilla.urls import reverse_lazy
from horilla_activity.models import Activity
from horilla_core.mixins import OwnerQuerysetMixin
from horilla_core.models import HorillaContentType
from horilla_generics.forms import HorillaModelForm


class MeetingsForm(OwnerQuerysetMixin, HorillaModelForm):
    """Form for filtering meetings"""

    class Meta:
        """
        Meta class for MeetingsForm
        """

        model = Activity
        fields = [
            "object_id",
            "content_type",
            "title",
            "subject",
            "status",
            "owner",
            "start_datetime",
            "end_datetime",
            "participants",
            "meeting_host",
            "is_all_day",
            "activity_type",
        ]

        widgets = {
            "is_all_day": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                    "hx-trigger": "click",
                    "hx-swap": "outerHTML",
                    "hx-select": "#activity-form-view",
                    "hx-include": "#activity-form-view",
                    "hx-target": "#activity-form-view",
                }
            ),
            "object_id": forms.HiddenInput(),
            "content_type": forms.HiddenInput(),
            "activity_type": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["is_all_day"].widget.attrs.update(
                {
                    "hx-get": (
                        f"/activity/meeting-update-form/{self.instance.pk}/"
                        "?toggle_is_all_day=true"
                    )
                }
            )
        else:
            self.fields["is_all_day"].widget.attrs.update(
                {"hx-get": "/activity/meeting-create-form/"}
            )

        is_all_day = (
            self.data.get("is_all_day", False)
            if self.data
            else self.initial.get("is_all_day")
        )
        if is_all_day == "on":  # Checkbox returns 'on' when checked
            is_all_day = True
        elif is_all_day in ("off", False):
            is_all_day = False

        # Update widget visibility based on current is_all_day value
        if is_all_day:
            self.fields["start_datetime"].widget = forms.HiddenInput()
            self.initial["start_datetime"] = None
            self.fields["end_datetime"].widget = forms.HiddenInput()
            self.initial["end_datetime"] = None

    def clean(self):
        cleaned_data = super().clean()
        start_datetime = cleaned_data.get("start_datetime")
        end_datetime = cleaned_data.get("end_datetime")
        is_all_day = cleaned_data.get("is_all_day")

        if not is_all_day and start_datetime and end_datetime:
            if start_datetime.date() == end_datetime.date():
                if start_datetime.time() >= end_datetime.time():
                    raise ValidationError(
                        {
                            "end_datetime": (
                                "End time must be later than start time "
                                "on the same date."
                            )
                        }
                    )
            elif end_datetime <= start_datetime:
                # Different dates: validate full datetime
                raise ValidationError(
                    {
                        "end_datetime": "End date and time must be later than start date and time."
                    }
                )
        return cleaned_data


class LogCallForm(OwnerQuerysetMixin, HorillaModelForm):
    """Form for filtering log calls"""

    class Meta:
        """
        Meta class for LogCallForm
        """

        model = Activity
        fields = [
            "object_id",
            "content_type",
            "subject",
            "owner",
            "call_purpose",
            "call_type",
            "call_duration_display",
            "status",
            "notes",
            "activity_type",
        ]
        widgets = {
            "call_duration_display": forms.TextInput(
                attrs={
                    "placeholder": "HH:MM:SS",
                    "title": "Enter duration in HH:MM:SS format",
                    "pattern": r"^\d{1,2}:\d{2}:\d{2}$",  # optional HTML5 pattern
                }
            ),
            "object_id": forms.HiddenInput(),
            "content_type": forms.HiddenInput(),
            "activity_type": forms.HiddenInput(),
        }

    def clean_call_duration_display(self):
        """
        Clean and validate the call_duration_display field
        """
        display = self.cleaned_data.get("call_duration_display")
        if display:
            parts = display.split(":")
            if len(parts) != 3:
                raise ValidationError("Duration must be in HH:MM:SS format")
            try:
                h, m, s = map(int, parts)
            except ValueError as exc:
                raise ValidationError(
                    "Hours, minutes, and seconds must be integers"
                ) from exc
            if h < 0 or not 0 <= m < 60 or not 0 <= s < 60:
                raise ValidationError(
                    "Hours must be >= 0; minutes and seconds must be between 00 and 59"
                )
        return display

    def clean(self):
        cleaned_data = super().clean()
        display = cleaned_data.get("call_duration_display")

        if display:
            try:
                h, m, s = map(int, display.split(":"))
                cleaned_data["call_duration_seconds"] = h * 3600 + m * 60 + s
            except Exception:
                self.add_error("call_duration_display", "Invalid HH:MM:SS format")
        return cleaned_data


class EventForm(OwnerQuerysetMixin, HorillaModelForm):
    """Form for filtering meetings"""

    class Meta:
        """
        Meta class for EventForm
        """

        model = Activity
        fields = [
            "object_id",
            "content_type",
            "title",
            "subject",
            "owner",
            "status",
            "start_datetime",
            "end_datetime",
            "location",
            "assigned_to",
            "status",
            "is_all_day",
            "activity_type",
        ]

        widgets = {
            "is_all_day": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                    "hx-trigger": "click",
                    "hx-swap": "outerHTML",
                    "hx-select": "#activity-form-view",
                    "hx-include": "#activity-form-view",
                    "hx-target": "#activity-form-view",
                }
            ),
            "object_id": forms.HiddenInput(),
            "content_type": forms.HiddenInput(),
            "activity_type": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["is_all_day"].widget.attrs.update(
                {
                    "hx-get": (
                        f"/activity/event-update-form/{self.instance.pk}/"
                        "?toggle_is_all_day=true"
                    )
                }
            )
        else:
            self.fields["is_all_day"].widget.attrs.update(
                {"hx-get": "/activity/event-create-form/"}
            )

        is_all_day = (
            self.data.get("is_all_day", False)
            if self.data
            else self.initial.get("is_all_day")
        )
        if is_all_day == "on":  # Checkbox returns 'on' when checked
            is_all_day = True
        elif is_all_day in ("off", False):
            is_all_day = False

        # Update widget visibility based on current is_all_day value
        if is_all_day:
            self.fields["start_datetime"].widget = forms.HiddenInput()
            self.initial["start_datetime"] = None
            self.fields["end_datetime"].widget = forms.HiddenInput()
            self.initial["end_datetime"] = None

    def clean(self):
        cleaned_data = super().clean()
        start_datetime = cleaned_data.get("start_datetime")
        end_datetime = cleaned_data.get("end_datetime")
        is_all_day = cleaned_data.get("is_all_day")

        if not is_all_day and start_datetime and end_datetime:
            if start_datetime.date() == end_datetime.date():
                if start_datetime.time() >= end_datetime.time():
                    raise ValidationError(
                        {
                            "end_datetime": (
                                "End time must be later than start time "
                                "on the same date."
                            )
                        }
                    )
            elif end_datetime <= start_datetime:
                # Different dates: validate full datetime
                raise ValidationError(
                    {
                        "end_datetime": "End date and time must be later than start date and time."
                    }
                )
        return cleaned_data


class ActivityCreateForm(OwnerQuerysetMixin, HorillaModelForm):
    """
    Activity creation and update form
    """

    class Meta:
        """
        meta class for ActivityCreateForm
        """

        model = Activity
        fields = "__all__"
        exclude = [
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "additional_info",
        ]
        widgets = {
            "activity_type": forms.Select(
                attrs={
                    "hx-target": "#activity-form-view-container",
                    "hx-swap": "outerHTML",
                    "data-placeholder": "Select Activity Type",
                    "hx-include": '[name="activity_type"]',
                    "id": "id_activity_type",
                }
            ),
            "is_all_day": forms.CheckboxInput(
                attrs={
                    "hx-target": "#activity-form-view-container",
                    "hx-swap": "outerHTML",
                    "hx-include": "#activity-form-view",
                    "id": "id_is_all_day",
                }
            ),
            "content_type": forms.Select(
                attrs={
                    "hx-target": "#activity-form-view-container",
                    "hx-swap": "outerHTML",
                    "hx-include": "#activity-form-view",
                    "id": "id_content_type",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        # Optional list of fields that should remain visible;
        # other fields will be hidden by this form.
        visible_fields = kwargs.pop("visible_fields", None)
        super().__init__(*args, **kwargs)

        if self.request and self.request.GET.get("view") == "calendar":
            self.fields["activity_type"].choices = [
                (value, label)
                for value, label in self.fields["activity_type"].choices
                if value not in ("log_call", "email")
            ]

        # Get activity_type from initial, submitted data, or instance
        activity_type = (
            self.data.get("activity_type")
            if self.data
            else self.initial.get("activity_type")
            or (self.instance.activity_type if self.instance.pk else None)
        )

        # Base URL for hx-get
        base_url = (
            f"/activity/activity-edit-form/{self.instance.pk}/?toggle_is_all_day=true"
            if self.instance.pk
            else "/activity/activity-create-form/"
        )

        current_content_type_id = (
            self.data.get("content_type")
            if self.data
            else self.initial.get("content_type")
        )
        if not current_content_type_id and self.instance.pk:
            current_content_type_id = self.instance.content_type_id

        if current_content_type_id and "content_type" in self.fields:
            resolved_content_type_id = (
                current_content_type_id.id
                if hasattr(current_content_type_id, "id")
                else current_content_type_id
            )
            self.initial["content_type"] = resolved_content_type_id
            self.fields["content_type"].initial = resolved_content_type_id
            self.fields["content_type"].widget.attrs["data-initial"] = str(
                resolved_content_type_id
            )

        # Update widget attributes for fields that are always present
        self.fields["activity_type"].widget.attrs.update({"hx-get": base_url})
        self.fields["content_type"].widget.attrs.update({"hx-get": base_url})

        # Handle is_all_day for event and meeting only
        if activity_type in ["event", "meeting"]:
            if "is_all_day" in self.fields:
                self.fields["is_all_day"].widget.attrs.update({"hx-get": base_url})

                is_all_day = (
                    self.data.get("is_all_day", False)
                    if self.data
                    else self.initial.get("is_all_day", False)
                )
                if is_all_day == "on":
                    is_all_day = True
                elif is_all_day == "off" or is_all_day is False:
                    is_all_day = False

                if is_all_day:
                    for field_name in ["start_datetime", "end_datetime"]:
                        if field_name in self.fields:
                            self.fields[field_name].widget = forms.HiddenInput()
                            self.initial[field_name] = None
                            self.fields[field_name].widget.attrs[
                                "data-hidden-label"
                            ] = "true"
        else:
            # Explicitly hide start_datetime and end_datetime for other activity types
            for field_name in ["start_datetime", "end_datetime", "is_all_day"]:
                if field_name in self.fields:
                    self.fields[field_name].widget = forms.HiddenInput()
                    self.initial[field_name] = None
                    self.fields[field_name].required = False

        if hasattr(self, "initial") and "activity_type" in self.initial:
            self.fields["activity_type"].initial = self.initial["activity_type"]

        content_type_id = current_content_type_id
        field_name = "object_id"
        submitted_values = self.data.getlist(field_name) if self.data else None
        initial_value = self.initial.get(field_name, None)

        object_id_attrs = {
            "id": f"id_{field_name}",
            "data-placeholder": "Select Related Object",
            "class": "select2-pagination w-full text-sm",
            "data-field-name": field_name,
        }

        if content_type_id:
            try:
                content_type = HorillaContentType.objects.get(id=content_type_id)
                app_label = content_type.app_label
                model_name = content_type.model
                object_id_attrs["data-url"] = reverse_lazy(
                    "horilla_generics:model_select2",
                    kwargs={"app_label": app_label, "model_name": model_name},
                )
                if submitted_values or initial_value:
                    object_id_attrs["data-initial"] = ",".join(
                        map(str, submitted_values or [initial_value])
                    )
                model_class = content_type.model_class()
                if model_class:
                    objects = model_class.objects.all()[:100]
                    self.fields["object_id"].choices = [
                        ("", "Select Related Object")
                    ] + [(obj.id, str(obj)) for obj in objects]
            except HorillaContentType.DoesNotExist:
                object_id_attrs["data-url"] = ""
                self.fields["object_id"].choices = [("", "Select Related Object")]
        else:
            object_id_attrs["data-url"] = ""
            self.fields["object_id"].choices = [("", "Select Related Object")]

        self.fields["object_id"].widget = forms.Select(attrs=object_id_attrs)

        if visible_fields is not None:
            ordered_fields = OrderedDict()
            # Add visible fields in requested order
            for name in visible_fields:
                if name in self.fields:
                    ordered_fields[name] = self.fields[name]
            # Append any remaining fields (typically hidden/meta fields)
            for name, field in self.fields.items():
                if name not in ordered_fields:
                    ordered_fields[name] = field
            self.fields = ordered_fields

            # Hide non-visible fields
            for name, field in self.fields.items():
                if name not in visible_fields:
                    field.widget = forms.HiddenInput()
                    field.required = False

    def clean(self):
        cleaned_data = super().clean()
        start_datetime = cleaned_data.get("start_datetime")
        end_datetime = cleaned_data.get("end_datetime")
        is_all_day = cleaned_data.get("is_all_day")
        content_type = cleaned_data.get("content_type")
        object_id = cleaned_data.get("object_id")

        # Validate object_id against content_type with owner filtration
        if content_type and object_id:
            try:
                model_class = content_type.model_class()

                # Apply owner filtration validation
                if self.request and self.request.user:
                    user = self.request.user

                    # Get fresh filtered queryset
                    queryset = model_class.objects.all()

                    if model_class is User:
                        allowed_user_ids = self._get_allowed_user_ids(user)
                        queryset = queryset.filter(id__in=allowed_user_ids)
                    elif (
                        hasattr(model_class, "OWNER_FIELDS")
                        and model_class.OWNER_FIELDS
                    ):
                        allowed_user_ids = self._get_allowed_user_ids(user)
                        if allowed_user_ids:
                            query = Q()
                            for owner_field in model_class.OWNER_FIELDS:
                                query |= Q(
                                    **{f"{owner_field}__id__in": allowed_user_ids}
                                )
                            queryset = queryset.filter(query)
                        else:
                            queryset = queryset.none()

                    # Check if the selected object exists in the filtered queryset
                    if not queryset.filter(id=object_id).exists():
                        raise ValidationError(
                            {
                                "object_id": (
                                    "Select a valid choice. That choice is not "
                                    "one of the available choices."
                                )
                            }
                        )

            except ValidationError:
                raise
            except Exception as exc:
                raise ValidationError(
                    {"object_id": "Invalid object selection."}
                ) from exc

        # Existing date/time validation
        if not is_all_day and start_datetime and end_datetime:
            if start_datetime.date() == end_datetime.date():
                if start_datetime.time() >= end_datetime.time():
                    raise ValidationError(
                        {
                            "end_datetime": (
                                "End time must be later than start time "
                                "on the same date."
                            )
                        }
                    )
            elif end_datetime <= start_datetime:
                raise ValidationError(
                    {
                        "end_datetime": "End date and time must be later than start date and time."
                    }
                )
        return cleaned_data

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
