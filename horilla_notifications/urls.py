"""
URL configuration for horilla_notifications app.

This module defines URL patterns for notification-related views, including:
- Marking notifications as read (single or all)
- Deleting notifications (single or all)
- Opening/redirecting to notification URLs
"""

# Third party imports (Django)
from django.urls import path

# Local application imports
from . import notification_template, views

app_name = "horilla_notifications"

urlpatterns = [
    path(
        "notifications-read/<int:pk>/",
        views.MarkNotificationReadView.as_view(),
        name="mark_read",
    ),
    path(
        "notifications-all-read/",
        views.MarkAllNotificationsReadView.as_view(),
        name="mark_all_read",
    ),
    path(
        "notification-delete/<int:pk>/",
        views.DeleteNotification.as_view(),
        name="notification_delete",
    ),
    path(
        "notification-all-delete/",
        views.DeleteAllNotification.as_view(),
        name="notification_all_delete",
    ),
    path(
        "open-notification/<int:pk>/",
        views.OpenNotificationView.as_view(),
        name="open_notification",
    ),
    # Notification Template Urls
    path(
        "notification-template-view/",
        notification_template.NotificationTemplateView.as_view(),
        name="notification_template_view",
    ),
    path(
        "notification_template_nav_view/",
        notification_template.NotificationTemplateNavbar.as_view(),
        name="notification_template_nav_view",
    ),
    path(
        "notification_template_list_view/",
        notification_template.NotificationTemplateListView.as_view(),
        name="notification_template_list_view",
    ),
    path(
        "notification_template_detail_view/<int:pk>/",
        notification_template.MailTemplateDetailView.as_view(),
        name="notification_template_detail_view",
    ),
    path(
        "notification_template_create_view/",
        notification_template.NotificationTemplateCreateUpdateView.as_view(),
        name="notification_template_create_view",
    ),
    path(
        "notification_template_update_view/<int:pk>/",
        notification_template.NotificationTemplateCreateUpdateView.as_view(),
        name="notification_template_update_view",
    ),
    path(
        "notification_template_delete_view/<int:pk>/",
        notification_template.NotificationTemplateDeleteView.as_view(),
        name="notification_template_delete_view",
    ),
    path(
        "field-selection/",
        notification_template.NotificationTemplateFieldSelectionView.as_view(),
        name="field_selection",
    ),
]
