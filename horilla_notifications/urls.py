"""
URL configuration for horilla_notifications app.

This module defines URL patterns for notification-related views, including:
- Marking notifications as read (single or all)
- Deleting notifications (single or all)
- Opening/redirecting to notification URLs
"""

# First-party / Horilla imports
from horilla.urls import path

# Local application imports
from horilla_notifications import views

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
        views.NotificationTemplateView.as_view(),
        name="notification_template_view",
    ),
    path(
        "notification_template_nav_view/",
        views.NotificationTemplateNavbar.as_view(),
        name="notification_template_nav_view",
    ),
    path(
        "notification_template_list_view/",
        views.NotificationTemplateListView.as_view(),
        name="notification_template_list_view",
    ),
    path(
        "notification_template_detail_view/<int:pk>/",
        views.NotificationTemplateDetailView.as_view(),
        name="notification_template_detail_view",
    ),
    path(
        "notification_template_create_view/",
        views.NotificationTemplateCreateUpdateView.as_view(),
        name="notification_template_create_view",
    ),
    path(
        "notification_template_update_view/<int:pk>/",
        views.NotificationTemplateCreateUpdateView.as_view(),
        name="notification_template_update_view",
    ),
    path(
        "notification_template_delete_view/<int:pk>/",
        views.NotificationTemplateDeleteView.as_view(),
        name="notification_template_delete_view",
    ),
    path(
        "field-selection/",
        views.NotificationTemplateFieldSelectionView.as_view(),
        name="field_selection",
    ),
]
