"""
Celery tasks for asynchronous automation execution in the Horilla automations system.

This module provides background tasks for:
- Executing automations asynchronously without blocking the main thread
- Sending emails and notifications in the background
"""

import logging

from celery import shared_task

from horilla.auth.models import User
from horilla_automations.methods import execute_automation, trigger_automations
from horilla_automations.models import HorillaAutomation
from horilla_core.models import Company, HorillaContentType
from horilla_utils.middlewares import _thread_local

logger = logging.getLogger(__name__)


class MockRequest:
    """Mock request object for Celery tasks"""

    def __init__(self, user, company, request_info):
        """
        Initialize a mock request object for use in Celery tasks.

        Args:
            user: The user associated with the request
            company: The active company for the request
            request_info: Dictionary containing request metadata (meta, host, scheme)
        """
        self.user = user
        self.active_company = company
        self.META = request_info.get("meta", {})
        self._host = request_info.get("host", "")
        self.scheme = request_info.get("scheme", "https")
        self.is_anonymous = user is None

    def get_host(self):
        """Get host for use in templates"""
        return self._host

    def build_absolute_uri(self, location=None):
        """Build absolute URI for use in templates"""
        if location is None:
            return f"{self.scheme}://{self._host}/"
        if location.startswith("http"):
            return location
        return f"{self.scheme}://{self._host}{location}"


@shared_task(bind=True, max_retries=3)
def execute_automation_task(
    self,
    content_type_id,
    object_id,
    trigger_type,
    user_id=None,
    company_id=None,
    request_info=None,
):
    """
    Celery task to execute automations asynchronously.

    Args:
        content_type_id: ID of the HorillaContentType for the instance
        object_id: ID of the instance that triggered the automation
        trigger_type: Type of trigger ('on_create', 'on_update', 'on_delete')
        user_id: ID of the user who triggered the automation (optional)
        company_id: ID of the company (optional)
        request_info: Dictionary containing request metadata (optional)
    """
    try:
        # Get the content type and instance
        content_type = HorillaContentType.objects.get(pk=content_type_id)
        model_class = content_type.model_class()

        if not model_class:
            logger.error(
                "Model class not found for content_type_id %s", content_type_id
            )
            return f"Model class not found for content_type_id {content_type_id}"

        # Get the instance
        # For delete triggers, the instance may already be deleted, which is OK
        instance = None
        try:
            instance = model_class.objects.get(pk=object_id)
        except model_class.DoesNotExist:
            if trigger_type == "on_delete":
                # For delete triggers, the instance is already deleted
                # We'll still try to execute automations, but condition evaluation will be skipped
                logger.info(
                    "Instance %s of %s already deleted, proceeding with delete automation",
                    object_id,
                    model_class.__name__,
                )
            else:
                logger.warning(
                    "Instance %s of %s not found, skipping automation",
                    object_id,
                    model_class.__name__,
                )
                return f"Instance {object_id} not found"

        # Get user if provided
        user = None
        if user_id:
            try:
                user = User.objects.get(pk=user_id)
            except User.DoesNotExist:
                logger.warning("User %s not found", user_id)

        # Get company if provided
        company = None
        if company_id:
            try:
                company = Company.objects.get(pk=company_id)
            except Company.DoesNotExist:
                logger.warning("Company %s not found", company_id)

        # Set up thread local for context
        request_info = request_info or {}
        mock_request = MockRequest(user, company, request_info)
        setattr(_thread_local, "request", mock_request)

        try:

            if instance is None and trigger_type == "on_delete":
                automations = HorillaAutomation.objects.filter(
                    model=content_type, trigger="on_delete"
                )
                for automation in automations:
                    try:

                        minimal_instance = type(
                            "DeletedInstance",
                            (),
                            {
                                "pk": object_id,
                                "_meta": model_class._meta,
                                "__str__": lambda self: f"Deleted {model_class.__name__} {object_id}",
                            },
                        )()
                        # Execute without condition check for delete
                        execute_automation(
                            automation, minimal_instance, user, trigger_type
                        )
                    except Exception as e:
                        logger.error(
                            "Error executing delete automation %s : %s",
                            automation.title,
                            str(e),
                            exc_info=True,
                        )
            else:
                trigger_automations(instance, trigger_type=trigger_type, user=user)

            logger.info(
                "Successfully executed automations for %s (id=%s, trigger=%s)",
                model_class.__name__,
                object_id,
                trigger_type,
            )
            return f"Automations executed for {model_class.__name__} {object_id}"

        finally:
            # Clean up thread local
            if hasattr(_thread_local, "request"):
                delattr(_thread_local, "request")

    except Exception as e:
        logger.error(
            "Error executing automation task for %s (content_type_id=%s, object_id=%s ): %s",
            trigger_type,
            content_type_id,
            object_id,
            str(e),
            exc_info=True,
        )
        # Don't retry for certain errors (like instance not found)
        if "not found" in str(e).lower() or "DoesNotExist" in str(type(e).__name__):
            logger.warning("Skipping retry for non-retryable error: %s", str(e))
            return f"Task failed: {str(e)}"
        # Retry on other failures
        try:
            raise self.retry(exc=e, countdown=60)
        except Exception as retry_error:
            logger.error("Failed to retry task: %s", retry_error)
            return f"Task failed and retry failed: {str(e)}"
        # Note: raise self.retry() will cause Celery to retry the task,
        # so this function will be called again. The return below ensures
        # all code paths that complete normally return a value.
        return f"Task failed: {str(e)}"
