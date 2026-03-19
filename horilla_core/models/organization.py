"""
This module defines the organizational models for the Horilla CRM application
"""

# Standard library imports
import logging

# Django imports
from django.contrib.auth.models import Permission

# First-party / Horilla imports
from horilla.db import models
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

from .base import HorillaCoreModel

logger = logging.getLogger(__name__)


class Department(HorillaCoreModel):
    """
    Department model
    """

    department_name = models.CharField(
        max_length=50, blank=False, verbose_name=_("Department Name")
    )
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))

    class Meta:
        """
        Meta options for the Department model.
        """

        verbose_name = _("Department")
        verbose_name_plural = _("Departments")
        unique_together = (("department_name", "company"),)

    def __str__(self):
        return str(self.department_name)

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy(
            "horilla_core:department_update_form", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """
        This method to get delete url
        """

        return reverse_lazy(
            "horilla_core:department_delete_view", kwargs={"pk": self.pk}
        )


class Role(HorillaCoreModel):
    """
    Role model
    """

    role_name = models.CharField(max_length=255, verbose_name=_("Role"))
    parent_role = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subroles",
        verbose_name="Parent Role",
    )
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))
    permissions = models.ManyToManyField(
        Permission, blank=True, related_name="roles", verbose_name=_("Permissions")
    )

    class Meta:
        """
        Meta options for the Role model.
        """

        verbose_name = _("Role")
        verbose_name_plural = _("Roles")

    def __str__(self):
        return str(self.role_name)

    def get_delete_url(self):
        """
        This method to get delete url
        """
        return reverse_lazy("horilla_core:delete_role", kwargs={"pk": self.pk})

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy("horilla_core:edit_roles_view", kwargs={"pk": self.pk})


class TeamRole(HorillaCoreModel):
    """
    Team Role model
    """

    team_role_name = models.CharField(
        max_length=50, blank=False, verbose_name=_("Team Role Name")
    )
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))

    class Meta:
        """
        Meta options for the Team Role model.
        """

        verbose_name = _("Team Role")
        verbose_name_plural = _("Team Roles")

    def __str__(self):
        return str(self.team_role_name)

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy(
            "horilla_core:team_role_update_form", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """
        This method to get delete url
        """

        return reverse_lazy(
            "horilla_core:team_role_delete_view", kwargs={"pk": self.pk}
        )


class CustomerRole(HorillaCoreModel):
    """
    Customer Role model
    """

    customer_role_name = models.CharField(
        max_length=50, blank=False, verbose_name=_("Customer Role Name")
    )
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))

    class Meta:
        """
        Meta options for the Customer Role model.
        """

        verbose_name = _("Customer Role")
        verbose_name_plural = _("Customer Roles")

    def __str__(self):
        return str(self.customer_role_name)

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy(
            "horilla_core:customer_role_update_form", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """
        This method to get delete url
        """

        return reverse_lazy(
            "horilla_core:customer_role_delete_view", kwargs={"pk": self.pk}
        )


class PartnerRole(HorillaCoreModel):
    """
    Partner Role model
    """

    partner_role_name = models.CharField(
        max_length=50, blank=False, verbose_name=_("Partner Role Name")
    )
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))

    class Meta:
        """
        Meta options for the Partner Role model.
        """

        verbose_name = _("Partner Role")
        verbose_name_plural = _("Partner Roles")

    def __str__(self):
        return str(self.partner_role_name)

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy(
            "horilla_core:partner_role_update_form", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """
        This method to get delete url
        """

        return reverse_lazy(
            "horilla_core:partner_role_delete_view", kwargs={"pk": self.pk}
        )
