"""
Celery beat schedules for the Horilla Core app.

Defines periodic tasks used by the core system,
such as processing scheduled exports.
"""

from datetime import timedelta

HORILLA_BEAT_SCHEDULE = {
    "process-scheduled-exports": {
        "task": "horilla_core.tasks.process_scheduled_exports",
        "schedule": timedelta(seconds=10),
    },
}
