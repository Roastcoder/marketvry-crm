"""
Helper methods for horilla_generics.

Provides dynamic form resolution and other utilities used by generic views.
"""

from horilla_core.mixins import OwnerQuerysetMixin
from horilla_generics.forms import HorillaModelForm


def get_dynamic_form_for_model(model):
    """Return a dynamic ModelForm class for the given model with owner queryset support."""
    _model = model  # capture explicitly before class definition

    class ResolvedDynamicForm(OwnerQuerysetMixin, HorillaModelForm):
        """Dynamic ModelForm for the specified model, inheriting from OwnerQuerysetMixin and HorillaModelForm."""

        class Meta:
            """Meta class for the dynamic form, specifying the model and fields to include/exclude."""

            model = _model  # use the captured local variable
            fields = "__all__"
            exclude = [
                "created_at",
                "updated_at",
                "created_by",
                "updated_by",
                "additional_info",
            ]

    return ResolvedDynamicForm
