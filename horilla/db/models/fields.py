"""
Custom field classes used by ``horilla.db.models``.

This module currently provides an extended ``GenericForeignKey`` that
enhances Django's default implementation with the following features:

* Allows the ``content_type`` ForeignKey to reference ``ContentType``
  proxy models (e.g., ``HorillaContentType``) by relaxing Django's
  default validation check.
* Replaces Django's strict ``model == ContentType`` validation with
  ``issubclass(model, ContentType)`` to support proxy subclasses.
* Adds support for a custom ``verbose_name`` while preserving Django's
  normal behavior and system checks.
"""

from django.contrib.contenttypes.fields import (
    GenericForeignKey as DjangoGenericForeignKey,
)
from django.contrib.contenttypes.models import ContentType
from django.core import checks
from django.utils.translation import gettext_lazy as _


class GenericForeignKey(DjangoGenericForeignKey):
    """
    Extended GenericForeignKey that allows proxy models of ContentType
    and supports custom verbose_name.
    """

    def __init__(
        self,
        ct_field="content_type",
        fk_field="object_id",
        verbose_name=_("Related To"),
        for_concrete_model=True,
    ):
        self._custom_verbose_name = verbose_name
        super().__init__(ct_field, fk_field, for_concrete_model=for_concrete_model)

    def contribute_to_class(self, cls, name, **kwargs):
        super().contribute_to_class(cls, name, **kwargs)

        # Preserve custom verbose_name
        if self._custom_verbose_name:
            self.verbose_name = self._custom_verbose_name

    def _check_content_type_field(self):
        try:
            field = self.model._meta.get_field(self.ct_field)
        except Exception:
            return []

        if not field.is_relation:
            return [
                checks.Error(
                    f"'{self.model._meta.object_name}.{self.ct_field}' is not a ForeignKey.",
                    obj=self,
                    id="contenttypes.E001",
                )
            ]

        model = field.remote_field.model

        if not issubclass(model, ContentType):
            return [
                checks.Error(
                    f"'{self.model._meta.object_name}.{self.ct_field}' must be a "
                    "ForeignKey to ContentType or a proxy of it.",
                    obj=self,
                    id="contenttypes.E002",
                )
            ]

        return []
