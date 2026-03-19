"""
This module defines the ListColumnVisibility and DetailFieldVisibility models for managing user preferences.
"""

# Django imports
from django.conf import settings

# First-party / Horilla imports
from horilla.db import models
from horilla.registry.permission_registry import permission_exempt_model
from horilla.utils.translation import gettext_lazy as _


@permission_exempt_model
class ListColumnVisibility(models.Model):
    """
    List Column Visibility model to store user preferences for visible columns in list views.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        default="",
        verbose_name=_("Column User"),
        related_name="list_column",
    )
    model_name = models.CharField(max_length=100)
    app_label = models.CharField(max_length=100)
    url_name = models.CharField(max_length=100)
    visible_fields = models.JSONField(default=list)
    context = models.CharField(max_length=200, blank=True)
    removed_custom_fields = models.JSONField(default=list, blank=True)
    all_objects = models.Manager()

    class Meta:
        """
        Meta options for the ListColumnVisibility model.
        """

        unique_together = ("user", "app_label", "model_name", "context", "url_name")

    @property
    def translated_visible_fields(self):
        """
        Returns the list of visible fields with translations.
        """
        return [_(field) for field in self.visible_fields]

    @property
    def translated_removed_fields(self):
        """
        Returns the list of removed fields with translations.
        """
        return [_(field) for field in self.removed_custom_fields]

    def __str__(self):
        return f"{self.user.username} - {self.app_label}.{self.model_name}"


@permission_exempt_model
class DetailFieldVisibility(models.Model):
    """
    Model to store user preferences for detail view fields.
    Supports two sections: header_fields (summary) and details_fields (Details tab).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name=_("User"),
        related_name="detail_field_visibility",
    )
    model_name = models.CharField(max_length=100)
    app_label = models.CharField(max_length=100)
    url_name = models.CharField(max_length=100, default="")
    header_fields = models.JSONField(default=list)  # [[verbose_name, field_name], ...]
    details_fields = models.JSONField(default=list)  # [[verbose_name, field_name], ...]
    all_objects = models.Manager()

    class Meta:
        """
        Meta options for the DetailFieldVisibility model.
        """

        unique_together = ("user", "app_label", "model_name", "url_name")

    def __str__(self):
        return f"{self.user.username} - {self.app_label}.{self.model_name} detail"
