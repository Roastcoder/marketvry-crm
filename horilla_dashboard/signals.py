"""
Signal handlers for the horilla_dashboard app.

This module contains Django signal receivers related to dashboard lifecycle
events (e.g., pre/post-save behavior).
"""

# Third-party imports
from django.db.models.signals import post_save
from django.dispatch import receiver

from horilla.auth.models import User

# First-party imports
from horilla.urls import reverse_lazy
from horilla_keys.models import ShortcutKey


# Define your  signals here
@receiver(post_save, sender=User)
def create_dashboard_shortcuts(sender, instance, created, **kwargs):
    """
    Add default dashboard shortcut keys for newly created users.

    This signal handler runs after a User is saved and ensures that a predefined
    set of `ShortcutKey` entries exist for the user (creates them if missing).
    """
    predefined = [
        {
            "page": str(reverse_lazy("horilla_dashboard:dashboard_list_view")),
            "key": "D",
            "command": "alt",
        },
    ]

    for item in predefined:
        ShortcutKey.all_objects.get_or_create(
            user=instance,
            key=item["key"],
            command=item["command"],
            defaults={
                "page": item["page"],
                "company": instance.company,
            },
        )
