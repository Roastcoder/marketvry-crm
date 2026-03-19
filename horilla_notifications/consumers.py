"""
WebSocket consumers for real-time notifications.

This module provides WebSocket consumers for handling real-time notification
delivery to authenticated users via Django Channels.
"""

import json

from channels.generic.websocket import AsyncWebsocketConsumer


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time notification delivery.

    This consumer handles WebSocket connections for authenticated users,
    allowing them to receive real-time notifications through a dedicated
    channel group per user.
    """

    async def connect(self):
        """
        Handle WebSocket connection.

        Authenticates the user and adds them to their notification channel group.
        Closes the connection if the user is anonymous.
        """
        user = self.scope["user"]
        if user.is_anonymous:
            await self.close()
            return

        self.group_name = f"notifications_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        """
        Handle WebSocket disconnection.

        Args:
            close_code: The WebSocket close code.
        """
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notification_message(self, event):
        """
        Send notification message to the WebSocket client.

        Args:
            event: Dictionary containing notification data with keys:
                - message: Notification message text
                - created_at: Timestamp when notification was created
                - sender: Sender information
                - id: Notification ID
                - open_url: URL to open when notification is clicked
        """
        await self.send(
            text_data=json.dumps(
                {
                    "message": event["message"],
                    "created_at": event["created_at"],
                    "sender": event["sender"],
                    "id": event["id"],
                    "open_url": event["open_url"],
                }
            )
        )
