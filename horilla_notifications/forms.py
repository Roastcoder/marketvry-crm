# Define your notifications forms here
"""
Forms for Horilla Notification module.

This module contains Django forms for managing email templates,
mail configurations, and mail-related functionality.
"""
from django import forms

from .models import NotificationTemplate


class NotificationTemplateForm(forms.ModelForm):
    """Form for creating and editing Horilla notification Templates"""

    class Meta:
        """Meta class for HorillaMailTemplateForm."""

        model = NotificationTemplate
        fields = ["title", "content_type", "message", "company"]

    def clean_title(self):
        """
        Clean and validate the title field.

        Returns:
            str: The cleaned and stripped title.

        Raises:
            ValidationError: If the title is empty or contains only whitespace.
        """
        title = self.cleaned_data.get("title")
        if not title or title.strip() == "":
            raise forms.ValidationError("Template title is required.")
        return title.strip()

    def clean_message(self):
        """
        Clean and validate the message field.

        Returns:
            str: The cleaned message content.

        Raises:
            ValidationError: If the message is empty or contains only whitespace.
        """
        message = self.cleaned_data.get("message")
        if not message or message.strip() == "":
            raise forms.ValidationError("Template message is required.")
        return message
