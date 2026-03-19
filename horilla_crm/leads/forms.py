"""Forms for Lead model and Lead conversion process."""

# Standard library imports
import logging

# Third-party imports
import pycountry

# Third-party imports (Django)
from django import forms

from horilla.auth.models import User

# First-party / Horilla imports
from horilla.urls import reverse, reverse_lazy
from horilla_core.mixins import OwnerQuerysetMixin
from horilla_crm.accounts.models import Account
from horilla_crm.contacts.models import Contact
from horilla_crm.opportunities.models import Opportunity
from horilla_generics.forms import HorillaModelForm, HorillaMultiStepForm
from horilla_mail.models import HorillaMailConfiguration

# Local application imports
from .models import (
    EmailToLeadConfig,
    Lead,
    LeadStatus,
    ScoringCondition,
    ScoringCriterion,
)

logger = logging.getLogger(__name__)


class LeadFormClass(OwnerQuerysetMixin, HorillaMultiStepForm):
    """Form class for Lead model"""

    class Meta:
        """Meta class for LeadFormClass"""

        model = Lead
        fields = "__all__"

    step_fields = {
        1: [
            "lead_owner",
            "title",
            "first_name",
            "last_name",
            "email",
            "contact_number",
            "fax",
            "lead_source",
            "lead_status",
        ],
        2: ["lead_company", "no_of_employees", "industry", "annual_revenue"],
        3: ["country", "state", "city", "zip_code"],
        4: ["requirements"],
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.current_step < len(self.step_fields):
            self.fields["created_by"].required = False
            self.fields["updated_by"].required = False

        self.fields["lead_status"].queryset = LeadStatus.objects.filter(is_final=False)
        self.fields["country"].widget.attrs.update(
            {
                "hx-get": reverse_lazy("horilla_core:get_country_subdivisions"),
                "hx-target": "#id_state",
                "hx-trigger": "change",
                "hx-swap": "innerHTML",
            }
        )
        self.fields["state"] = forms.ChoiceField(
            choices=[],
            required=False,
            widget=forms.Select(
                attrs={"id": "id_state", "class": "js-example-basic-single headselect"}
            ),
        )

        if "country" in self.data:
            country_code = self.data.get("country")
            self.fields["state"].choices = self.get_subdivision_choices(country_code)
        elif self.instance.pk and self.instance.country:
            self.fields["state"].choices = self.get_subdivision_choices(
                self.instance.country.code
            )

    def get_subdivision_choices(self, country_code):
        """Get subdivision choices for a given country code."""
        try:
            subdivisions = list(
                pycountry.subdivisions.get(country_code=country_code.upper())
            )
            return [(sub.code, sub.name) for sub in subdivisions]
        except Exception:
            return []


class LeadSingleForm(OwnerQuerysetMixin, HorillaModelForm):
    """
    Custom form for Lead to add HTMX attributes
    Inherits from HorillaModelForm to preserve all existing behavior.
    """

    class Meta:
        """Meta class for LeadStatusForm"""

        model = Lead
        fields = [
            "lead_owner",
            "title",
            "first_name",
            "last_name",
            "email",
            "contact_number",
            "lead_source",
            "lead_status",
            "lead_company",
            "no_of_employees",
            "industry",
            "annual_revenue",
            "country",
            "state",
            "city",
            "zip_code",
            "fax",
            "requirements",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lead_status"].queryset = LeadStatus.objects.filter(is_final=False)
        self.fields["country"].widget.attrs.update(
            {
                "hx-get": reverse_lazy("horilla_core:get_country_subdivisions"),
                "hx-target": "#id_state",
                "hx-trigger": "change",
                "hx-swap": "innerHTML",
            }
        )
        self.fields["state"] = forms.ChoiceField(
            choices=[],
            required=False,
            widget=forms.Select(
                attrs={"id": "id_state", "class": "js-example-basic-single headselect"}
            ),
        )

        if "country" in self.data:
            country_code = self.data.get("country")
            self.fields["state"].choices = self.get_subdivision_choices(country_code)
        elif self.instance.pk and self.instance.country:
            self.fields["state"].choices = self.get_subdivision_choices(
                self.instance.country.code
            )

    def get_subdivision_choices(self, country_code):
        """Get subdivision choices for a given country code."""
        try:
            subdivisions = list(
                pycountry.subdivisions.get(country_code=country_code.upper())
            )
            return [(sub.code, sub.name) for sub in subdivisions]
        except Exception:
            return []


class LeadConversionForm(forms.Form):
    """Form for converting a Lead into Account, Contact, and Opportunity"""

    # Account fields
    account_action = forms.ChoiceField(
        choices=[("create_new", "Create New"), ("select_existing", "Select Existing")],
        widget=forms.RadioSelect(
            attrs={
                "class": "border border-[#cbcbcb] w-3 h-3 text-[#e54f38] bg-white focus:ring-[#e54f38] cursor-pointer"
            }
        ),
        initial="create_new",
    )
    account_name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "text-color-600 p-2 placeholder:text-xs  w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                "placeholder": "Enter Account Name",
            }
        ),
    )
    existing_account = forms.ModelChoiceField(
        queryset=Account.objects.all(),
        required=False,
        empty_label="Select Account",
        widget=forms.Select(
            attrs={
                "class": "select2-pagination w-full text-sm",
                "hx-get": "",  # Will be set dynamically
                "hx-target": "#opportunity-field",
                "hx-swap": "innerHTML",
                "hx-trigger": "change",
            }
        ),
    )

    # Contact fields
    contact_action = forms.ChoiceField(
        choices=[("create_new", "Create New"), ("select_existing", "Select Existing")],
        widget=forms.RadioSelect(
            attrs={
                "class": "border border-[#cbcbcb] w-3 h-3 text-[#e54f38] bg-white focus:ring-[#e54f38] cursor-pointer"
            }
        ),
        initial="create_new",
    )
    first_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                "placeholder": "Enter First Name",
            }
        ),
    )
    last_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                "placeholder": "Enter Last Name",
            }
        ),
    )
    existing_contact = forms.ModelChoiceField(
        queryset=Contact.objects.all(),
        required=False,
        empty_label="Select Contact",
        widget=forms.Select(attrs={"class": "normal-seclect"}),
    )

    # Opportunity fields
    opportunity_action = forms.ChoiceField(
        choices=[("create_new", "Create New"), ("select_existing", "Select Existing")],
        widget=forms.RadioSelect(
            attrs={
                "class": "border border-[#cbcbcb] w-3 h-3 text-[#e54f38] bg-white focus:ring-[#e54f38] cursor-pointer"
            }
        ),
        initial="create_new",
    )
    opportunity_name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                "placeholder": "Enter Opportunity Name",
            }
        ),
    )
    existing_opportunity = forms.ModelChoiceField(
        queryset=Opportunity.objects.none(),  # Start with empty queryset
        required=False,
        empty_label="Select Opportunity",
        widget=forms.Select(attrs={"class": "normal-seclect"}),
    )

    # Owner field
    owner = forms.ModelChoiceField(
        queryset=User.objects.all(),
        required=True,
        empty_label="Select Owner",
        widget=forms.Select(
            attrs={
                "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600"
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        self.lead = kwargs.pop("lead", None)
        self.selected_account = kwargs.pop("selected_account", None)
        super().__init__(*args, **kwargs)

        if self.lead:
            # Pre-populate fields with lead data
            self.fields["account_name"].initial = self.lead.lead_company
            self.fields["first_name"].initial = self.lead.first_name
            self.fields["last_name"].initial = self.lead.last_name
            self.fields["opportunity_name"].initial = (
                f"{self.lead.lead_company} - Opportunity"
            )
            self.fields["owner"].initial = self.lead.lead_owner

            # Set HTMX URL for account selection
            self.fields["existing_account"].widget.attrs["hx-get"] = reverse(
                "leads:convert_lead", kwargs={"pk": self.lead.pk}
            )

        # Filter opportunities based on selected account
        if self.selected_account:
            self.fields["existing_opportunity"].queryset = Opportunity.objects.filter(
                account=self.selected_account
            )
        else:
            self.fields["existing_opportunity"].queryset = None

    def clean(self):
        cleaned_data = super().clean()

        # Validate account
        account_action = cleaned_data.get("account_action")
        if account_action == "create_new":
            if not cleaned_data.get("account_name"):
                self.add_error(
                    "account_name",
                    "Account name is required when creating new account.",
                )
        elif account_action == "select_existing":
            if not cleaned_data.get("existing_account"):
                self.add_error("existing_account", "Please select an existing account.")

        # Validate contact
        contact_action = cleaned_data.get("contact_action")
        if contact_action == "create_new":
            if not cleaned_data.get("first_name"):
                self.add_error(
                    "first_name", "First name is required when creating new contact."
                )
            if not cleaned_data.get("last_name"):
                self.add_error(
                    "last_name", "Last name is required when creating new contact."
                )
        elif contact_action == "select_existing":
            if not cleaned_data.get("existing_contact"):
                self.add_error("existing_contact", "Please select an existing contact.")

        # Validate opportunity
        opportunity_action = cleaned_data.get("opportunity_action")
        if opportunity_action == "create_new":
            if not cleaned_data.get("opportunity_name"):
                self.add_error(
                    "opportunity_name",
                    "Opportunity name is required when creating new opportunity.",
                )
        elif opportunity_action == "select_existing":
            if not cleaned_data.get("existing_opportunity"):
                self.add_error(
                    "existing_opportunity", "Please select an existing opportunity."
                )

        return cleaned_data


class LeadStatusForm(HorillaModelForm):
    """
    Custom form for LeadStatus to add HTMX attributes to is_final field.
    Inherits from HorillaModelForm to preserve all existing behavior.
    """

    class Meta:
        """Meta class for LeadStatusForm"""

        model = LeadStatus
        fields = ["name", "probability", "is_final", "order"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add HTMX attributes to is_final field to toggle order field visibility
        if "is_final" in self.fields:
            self.fields["is_final"].widget.attrs.update(
                {
                    "hx-post": reverse_lazy("leads:toggle_order_field"),
                    "hx-target": "#order_container",
                    "hx-swap": "outerHTML",
                    "hx-trigger": "change",
                }
            )


class EmailToLeadForm(HorillaModelForm):
    """
    Inherits from HorillaModelForm to preserve all existing behavior.
    """

    class Meta:
        """Meta class for LeadStatusForm"""

        model = EmailToLeadConfig
        fields = ["mail", "lead_owner", "accept_emails_from", "keywords"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["mail"].queryset = HorillaMailConfiguration.objects.filter(
            mail_channel="incoming", is_active=True
        )


class ScoringCriterionForm(HorillaModelForm):
    """Form for creating and editing scoring criteria."""

    def __init__(self, *args, **kwargs):
        """Initialize scoring criterion form with condition model."""
        kwargs["condition_model"] = ScoringCondition
        super().__init__(*args, **kwargs)

    def clean(self):
        """Process multiple condition rows from form data"""
        cleaned_data = super().clean()

        condition_rows = self._extract_condition_rows()

        if not condition_rows:
            raise forms.ValidationError("At least one condition must be provided.")

        cleaned_data["condition_rows"] = condition_rows

        return cleaned_data

    class Meta:
        """Meta options for ScoringCriterionForm."""

        model = ScoringCriterion
        fields = ["rule", "points", "operation_type"]
        widgets = {
            "points": forms.NumberInput(
                attrs={
                    "class": "text-color-600 p-2 w-full border border-dark-50 rounded-md mt-1"
                }
            ),
        }
