"""
Celery beat schedule configuration for horilla_mail app.

This module defines periodic tasks that are executed by Celery Beat,
including scheduled email processing tasks.
"""

from datetime import timedelta

HORILLA_BEAT_SCHEDULE = {
    "process-scheduled-mails-every-minute": {
        "task": "horilla_mail.tasks.process_scheduled_mails",
        "schedule": timedelta(seconds=10),
    },
}
