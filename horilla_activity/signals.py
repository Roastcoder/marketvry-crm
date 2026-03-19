"""Signal handlers for horilla_activity app."""

# Third-party imports (Django)
from django.db.models.signals import post_save
from django.dispatch import receiver

# First-party / Horilla imports
from horilla.auth.models import User
from horilla_keys.models import ShortcutKey


@receiver(post_save, sender=User)
def create_activity_shortcuts(sender, instance, created, **kwargs):
    """Create default activity shortcuts for new users."""
    predefined = [
        {"page": "/activity/activity-view/", "key": "Y", "command": "alt"},
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
