"""
This module provides helper methods for creating notifications and limiting content types for notifications in the Horilla framework. It includes a function to create notifications with optional linking to related objects, and a function to limit
"""

# Notification helper methods

from horilla_core.models import HorillaContentType

# First-party / Horilla apps
from horilla_notifications.models import Notification


def create_notification(
    user, message, sender=None, url=None, instance=None, read=False
):
    """
    Create and save a Notification, optionally linking it to a related object.

    When ``instance`` is provided, sets content_type and object_id so the
    notification detail popup can show that object's details when no URL is given.

    Args:
        user: User to notify (required).
        message: Notification message text (required).
        sender: User who triggered the notification (optional).
        url: Optional URL to redirect to when the notification is opened.
        instance: Optional model instance this notification is about (e.g. Department, Lead).
                  When provided, content_type and object_id are set from it.
        read: Whether the notification is read (default False).

    Returns:
        The created Notification instance, or None if creation failed.
    """
    content_type = None
    object_id = None
    if instance is not None:
        try:
            content_type = HorillaContentType.objects.get_for_model(instance)
            object_id = instance.pk
        except Exception:
            pass

    try:
        # Lazy import to avoid circular import

        notification = Notification(
            user=user,
            message=message,
            sender=sender,
            url=url or None,
            read=read,
            content_type=content_type,
            object_id=object_id,
        )
        notification.save()
        return notification
    except Exception:
        return None
