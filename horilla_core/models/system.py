"""
This module defines the system models for the Horilla CRM application,
including settings and about system information.
"""

# Standard library imports
import logging

# First-party / Horilla imports
from horilla.db import models
from horilla.registry.permission_registry import permission_exempt_model
from horilla.utils.translation import gettext_lazy as _

from .base import HorillaCoreModel

logger = logging.getLogger(__name__)


class HorillaSettings(models.Model):
    """
    Horilla Settings model for permission management
    """

    class Meta:
        """
        Meta options for the HorillaSettings model.
        """

        managed = False
        default_permissions = ()
        permissions = (("can_view_horilla_settings", _("Can View Global Settings")),)
        verbose_name = _("Global Settings")


class HorillaAboutSystem(models.Model):
    """
    Horilla About System model for permission management
    """

    class Meta:
        """
        Meta options for the HorillaAboutSystem model.
        """

        managed = False
        default_permissions = ()
        permissions = (("can_view_horilla_about_system", _("Can View About System")),)
        verbose_name = _("About System")


@permission_exempt_model
class ActiveTab(HorillaCoreModel):
    """
    ActiveTab
    """

    path = models.CharField(max_length=256)
    tab_target = models.CharField(max_length=256)
