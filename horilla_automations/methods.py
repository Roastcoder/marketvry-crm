"""
Methods for executing automations
"""

# Standard library imports
import logging
import threading
from urllib.parse import urlencode, urlparse

# Third-party imports (Django)
from django.db import transaction
from django.template import engines
from django.utils import timezone

# First-party / Horilla imports
from horilla.auth.models import User
from horilla_automations.models import HorillaAutomation
from horilla_core.models import HorillaContentType
from horilla_mail.models import HorillaMail, HorillaMailConfiguration
from horilla_mail.services import HorillaMailManager
from horilla_notifications.methods import create_notification
from horilla_utils.methods import get_section_info_for_model
from horilla_utils.middlewares import _thread_local

logger = logging.getLogger(__name__)


def _get_model_list_view_url(model_class):
    """
    Resolve the list/view URL for a model by finding a settings menu item
    whose permission matches the model's view permission (e.g. department -> department_view).
    Returns a path string or None if not found.
    """
    try:
        app_label = model_class._meta.app_label
        model_name = model_class._meta.model_name
        view_perm = f"{app_label}.view_{model_name}"
        from horilla.menu.settings_menu import settings_registry

        for cls in settings_registry:
            items = getattr(cls(), "items", [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                perm = item.get("perm")
                if perm != view_perm:
                    continue
                url = item.get("url")
                if url is None:
                    continue
                path = str(url).strip()
                if path and path != "#":
                    if not path.startswith("/"):
                        parsed = urlparse(path)
                        path = parsed.path or path
                    return path
        return None
    except Exception as e:
        logger.debug("_get_model_list_view_url(%s): %s", model_class.__name__, str(e))
        return None


def evaluate_condition(condition, instance):
    """
    Evaluate a single condition against an instance.

    Args:
        condition: AutomationCondition instance
        instance: Model instance to evaluate against

    Returns:
        bool: True if condition is met, False otherwise
    """
    try:
        # Get the field value from the instance
        field_value = getattr(instance, condition.field, None)

        # Get the field object to determine its type
        field = instance._meta.get_field(condition.field)

        # Check if field is numeric
        is_numeric_field = False
        field_type = None
        if hasattr(field, "get_internal_type"):
            field_type = field.get_internal_type()
            numeric_types = [
                "IntegerField",
                "BigIntegerField",
                "SmallIntegerField",
                "PositiveIntegerField",
                "PositiveSmallIntegerField",
                "DecimalField",
                "FloatField",
            ]
            is_numeric_field = field_type in numeric_types

        # Handle ForeignKey fields - get the ID
        if hasattr(field, "related_model"):
            # It's a ForeignKey
            if field_value:
                field_value = (
                    str(field_value.pk)
                    if hasattr(field_value, "pk")
                    else str(field_value)
                )
            else:
                field_value = ""
        else:
            # Convert field_value to string for comparison
            if field_value is None:
                field_value = ""
            else:
                field_value = str(field_value)

        value = condition.value or ""

        # For numeric fields with equals/not_equals, do numeric comparison
        if is_numeric_field and condition.operator in ["equals", "not_equals"]:
            try:
                # Convert both to float for comparison (handles Decimal, Float, Integer)
                field_num = float(field_value) if field_value else None
                value_num = float(value) if value else None

                if condition.operator == "equals":
                    # Handle None/empty values
                    if field_num is None and value_num is None:
                        return True
                    if field_num is None or value_num is None:
                        return False
                    return field_num == value_num
                if condition.operator == "not_equals":
                    # Handle None/empty values
                    if field_num is None and value_num is None:
                        return False
                    if field_num is None or value_num is None:
                        return True
                    return field_num != value_num
            except (ValueError, TypeError):
                # If conversion fails, fall back to string comparison
                pass

        # Perform comparison based on operator (string comparison for non-numeric or fallback)
        if condition.operator == "equals":
            return field_value == value
        if condition.operator == "not_equals":
            return field_value != value
        if condition.operator == "contains":
            return value.lower() in field_value.lower()
        if condition.operator == "not_contains":
            return value.lower() not in field_value.lower()
        if condition.operator == "starts_with":
            return field_value.lower().startswith(value.lower())
        if condition.operator == "ends_with":
            return field_value.lower().endswith(value.lower())
        if condition.operator == "greater_than":
            try:
                return float(field_value) > float(value)
            except (ValueError, TypeError):
                return False
        if condition.operator == "greater_than_equal":
            try:
                return float(field_value) >= float(value)
            except (ValueError, TypeError):
                return False
        if condition.operator == "less_than":
            try:
                return float(field_value) < float(value)
            except (ValueError, TypeError):
                return False
        if condition.operator == "less_than_equal":
            try:
                return float(field_value) <= float(value)
            except (ValueError, TypeError):
                return False
        if condition.operator == "is_empty":
            return not field_value or field_value.strip() == ""
        if condition.operator == "is_not_empty":
            return bool(field_value and field_value.strip())

        return False

    except Exception as e:
        logger.error("Error evaluating condition %s: %s", condition, str(e))
        return False


def evaluate_automation_conditions(automation, instance):
    """
    Evaluate all conditions for an automation against an instance.

    Args:
        automation: HorillaAutomation instance
        instance: Model instance to evaluate against

    Returns:
        bool: True if all conditions are met, False otherwise
    """
    conditions = automation.conditions.all().order_by("order", "created_at")

    if not conditions.exists():
        # No conditions means always execute
        return True

    result = None
    previous_logical_op = None

    for condition in conditions:
        condition_result = evaluate_condition(condition, instance)

        if result is None:
            # First condition
            result = condition_result
        else:
            # Apply logical operator
            if previous_logical_op == "or":
                result = result or condition_result
            else:  # default to "and"
                result = result and condition_result

        previous_logical_op = condition.logical_operator

    return result if result is not None else True


def resolve_mail_recipients(mail_to, instance, user):
    """
    Resolve mail recipients from the mail_to field.
    Supports dynamic field access like 'instance.owner.email' or 'self.email'.

    Args:
        mail_to: String containing recipient specification
        instance: Model instance
        user: User who triggered the automation

    Returns:
        list: List of email addresses
    """
    recipients = []

    # Split by comma to handle multiple recipients
    for recipient_spec in mail_to.split(","):
        recipient_spec = recipient_spec.strip()
        if not recipient_spec:
            continue

        try:
            # Handle 'self' keyword
            if recipient_spec == "self":
                if user and hasattr(user, "email") and user.email:
                    recipients.append(user.email)
                continue

            # Handle field paths like 'instance.owner.email' or 'instance.owner'
            if recipient_spec.startswith("instance."):
                field_path = recipient_spec.replace("instance.", "")
                value = instance
                for attr in field_path.split("."):
                    value = getattr(value, attr, None)
                    if value is None:
                        break

                # If value is a User object, get its email
                if value and hasattr(value, "email"):
                    recipients.append(value.email)
                # If value is already an email string
                elif isinstance(value, str) and "@" in value:
                    recipients.append(value)
            else:
                # Direct email address
                if "@" in recipient_spec:
                    recipients.append(recipient_spec)
        except Exception as e:
            logger.error("Error resolving recipient '%s': %s", recipient_spec, str(e))
            continue

    return recipients


def resolve_notification_users(mail_to, instance, user):
    """
    Resolve users for notifications from the mail_to field.
    Supports both email addresses and direct user field references.

    Args:
        mail_to: String containing recipient specification
        instance: Model instance
        user: User who triggered the automation

    Returns:
        list: List of User objects
    """
    users = []

    # Split by comma to handle multiple recipients
    for recipient_spec in mail_to.split(","):
        recipient_spec = recipient_spec.strip()
        if not recipient_spec:
            continue

        try:
            # Handle 'self' keyword - the user who triggered the automation
            if recipient_spec == "self":
                if user:
                    users.append(user)
                continue

            # Handle field paths like 'instance.owner' or 'instance.created_by'
            if recipient_spec.startswith("instance."):
                field_path = recipient_spec.replace("instance.", "")
                value = instance
                for attr in field_path.split("."):
                    value = getattr(value, attr, None)
                    if value is None:
                        break

                # If value is a User object, use it directly
                if value and hasattr(value, "email") and hasattr(value, "pk"):
                    # Check if it's a User model instance
                    if isinstance(value, User):
                        users.append(value)
                    elif hasattr(value, "email"):
                        # It's an object with email, try to find the user
                        try:
                            user_obj = User.objects.filter(email=value.email).first()
                            if user_obj:
                                users.append(user_obj)
                        except Exception:
                            pass
            else:
                # Direct email address - find user by email
                if "@" in recipient_spec:
                    try:
                        user_obj = User.objects.filter(email=recipient_spec).first()
                        if user_obj:
                            users.append(user_obj)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(
                "Error resolving notification user '%s': %s",
                recipient_spec,
                str(e),
                exc_info=True,
            )
            continue

    return users


def execute_automation(automation, instance, user=None, trigger_type="on_create"):
    """
    Execute an automation for a given instance.

    Args:
        automation: HorillaAutomation instance
        instance: Model instance that triggered the automation
        user: User who triggered the automation (optional)
        trigger_type: Type of trigger ('on_create', 'on_update', 'on_delete')
    """
    try:
        # Check if automation trigger matches
        # Handle 'on_create_or_update' option - it should trigger for both create and update
        if automation.trigger == "on_create_or_update":
            if trigger_type not in ["on_create", "on_update"]:
                return
        elif automation.trigger != trigger_type:
            return

        # Evaluate conditions (skip for delete operations if instance is minimal)
        # For delete operations, instance might be a minimal representation
        skip_conditions = (
            trigger_type == "on_delete"
            and hasattr(instance, "__class__")
            and instance.__class__.__name__ == "DeletedInstance"
        )

        if not skip_conditions:
            if not evaluate_automation_conditions(automation, instance):
                logger.info(
                    "Automation %s conditions not met for instance %s",
                    automation.title,
                    instance,
                )
                return

        # Get user from thread local if not provided
        if not user:
            request = getattr(_thread_local, "request", None)
            if request:
                user = getattr(request, "user", None)

        # Resolve recipients from mail_to field
        recipients = resolve_mail_recipients(automation.mail_to, instance, user)

        # Also add recipients from also_sent_to ManyToMany field
        if automation.also_sent_to.exists():
            also_sent_to_users = automation.also_sent_to.all()
            for also_user in also_sent_to_users:
                if also_user and hasattr(also_user, "email") and also_user.email:
                    email = also_user.email
                    if email not in recipients:
                        recipients.append(email)

        if not recipients:
            logger.warning("Automation %s has no valid recipients", automation.title)
            return

        # Prepare context for template rendering
        request = getattr(_thread_local, "request", None)
        context = {
            "instance": instance,
            "user": user,
            "self": user,  # 'self' refers to the user who triggered
        }

        if request:
            context["request"] = request
            context["active_company"] = getattr(request, "active_company", None)

        # Handle email delivery
        if automation.delivery_channel in ["mail", "both"]:
            send_automation_email(automation, instance, recipients, context, user)

        # Handle notification delivery
        if automation.delivery_channel in ["notification", "both"]:
            send_automation_notification(
                automation, instance, recipients, context, user
            )

    except Exception as e:
        logger.error(
            "Error executing automation %s: %s", automation.title, str(e), exc_info=True
        )


def send_automation_email(automation, instance, recipients, context, user):
    """
    Send email for an automation.

    Args:
        automation: HorillaAutomation instance
        instance: Model instance
        recipients: List of email addresses
        context: Template context
        user: User who triggered the automation
    """
    try:
        if not automation.mail_template:
            logger.warning("Automation %s has no mail template", automation.title)
            return

        # Create HorillaMail instance

        company = context.get("active_company") or (
            user.company if hasattr(user, "company") and user else None
        )

        content_type = HorillaContentType.objects.get_for_model(instance)

        # Get mail server - use the one selected in automation, or fall back to default
        sender = automation.mail_server

        # If no mail server selected in automation, use default logic
        if not sender:
            if company:
                sender = HorillaMailConfiguration.objects.filter(
                    company=company, mail_channel="outgoing", is_primary=True
                ).first()
                if not sender:
                    sender = HorillaMailConfiguration.objects.filter(
                        company=company, mail_channel="outgoing"
                    ).first()
            else:
                # Fallback to primary mail server if no company
                sender = HorillaMailConfiguration.objects.filter(
                    mail_channel="outgoing", is_primary=True
                ).first()

        mail = HorillaMail.objects.create(
            sender=sender,
            to=",".join(recipients),
            subject=automation.mail_template.subject or "",
            body=automation.mail_template.body or "",
            content_type=content_type,
            object_id=instance.pk,
            mail_status="draft",
            created_by=user,
            company=company,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )

        # Store context in mail's additional_info for async sending
        if not mail.additional_info:
            mail.additional_info = {}
        mail.additional_info["request_info"] = {
            "user_id": user.pk if user else None,
            "company_id": company.pk if company else None,
            "meta": {},
            "host": "",
            "scheme": "https",
        }
        mail.save(update_fields=["additional_info"])

        def send_email_thread():
            try:
                if sender:
                    setattr(_thread_local, "from_mail_id", sender.pk)

                from horilla_automations.tasks import MockRequest

                mock_request = MockRequest(user, company, {})
                setattr(_thread_local, "request", mock_request)

                # Send the mail using HorillaMailManager (uses horilla_backends)
                HorillaMailManager.send_mail(mail, context=context)

                mail.refresh_from_db()
                if mail.mail_status != "sent":
                    logger.error(
                        "Email failed to send via threading: %s (mail_id: %s), status: %s, message: %s",
                        automation.title,
                        mail.pk,
                        mail.mail_status,
                        mail.mail_status_message,
                    )
            except Exception as e:
                logger.error(
                    "Error sending email in thread for automation %s (mail_id: %s ): %s",
                    automation.title,
                    mail.pk,
                    str(e),
                    exc_info=True,
                )
                # Update mail status to failed
                try:
                    mail.refresh_from_db()
                    mail.mail_status = "failed"
                    mail.mail_status_message = str(e)
                    mail.save(update_fields=["mail_status", "mail_status_message"])
                except Exception:
                    pass
            finally:
                # Clean up thread local
                if hasattr(_thread_local, "from_mail_id"):
                    delattr(_thread_local, "from_mail_id")
                if hasattr(_thread_local, "request"):
                    delattr(_thread_local, "request")

        thread = threading.Thread(target=send_email_thread, daemon=True)
        thread.start()

    except Exception as e:
        logger.error(
            "Error sending automation email for %s: %s",
            automation.title,
            str(e),
            exc_info=True,
        )


def send_automation_notification(automation, instance, recipients, context, user):
    """
    Send notification for an automation.

    Args:
        automation: HorillaAutomation instance
        instance: Model instance
        recipients: List of email addresses (for reference, but we resolve users directly)
        context: Template context
        user: User who triggered the automation
    """
    try:
        # Use notification_template if available, otherwise fall back to mail_template for backward compatibility
        notification_template = automation.notification_template
        if not notification_template and automation.mail_template:
            # Fallback to mail_template for backward compatibility
            logger.warning(
                "Automation %s has no notification template, using mail template as fallback",
                automation.title,
            )
            notification_template = None  # Will use mail_template below

        if not notification_template and not automation.mail_template:
            logger.warning(
                "Automation %s  has no notification template or mail template",
                automation.title,
            )
            return

        users_to_notify = resolve_notification_users(automation.mail_to, instance, user)

        if automation.also_sent_to.exists():
            also_sent_to_users = automation.also_sent_to.all()
            for also_user in also_sent_to_users:
                if also_user and also_user not in users_to_notify:
                    users_to_notify.append(also_user)

        if not users_to_notify:
            logger.warning(
                "Automation %s has no valid users for notification", automation.title
            )
            return

        django_engine = engines["django"]

        # Use notification_template if available
        if notification_template:
            message_template = (notification_template.message or "").strip()
            notification_message = ""
            if message_template:
                message_template = "{% load horilla_tags %}\n" + message_template
                notification_message = django_engine.from_string(
                    message_template
                ).render(context)
            notification_message = (
                notification_message[:500]
                if notification_message
                else "Automation notification"
            )
        else:
            # Fallback to mail_template for backward compatibility
            subject_template = (automation.mail_template.subject or "").strip()
            body_template = (automation.mail_template.body or "").strip()

            notification_message = ""
            if subject_template:
                subject_template = "{% load horilla_tags %}\n" + subject_template
                subject = django_engine.from_string(subject_template).render(context)
                notification_message = subject

            if body_template:
                body_template = "{% load horilla_tags %}\n" + body_template
                body = django_engine.from_string(body_template).render(context)
                if notification_message:
                    notification_message += f"\n{body}"
                else:
                    notification_message = body

            notification_message = (
                notification_message[:500]
                if notification_message
                else "Automation notification"
            )

        instance_url = None
        for attr in dir(instance):
            if attr.startswith("get_detail_"):
                method = getattr(instance, attr)
                if callable(method):
                    try:
                        url = method()
                        if url and str(url).strip() and str(url) != "#":
                            instance_url = str(url).strip()
                            if not instance_url.startswith("/"):
                                parsed = urlparse(instance_url)
                                instance_url = parsed.path or instance_url
                            break
                    except Exception as e:
                        logger.debug("get_detail_* %s: %s", attr, str(e))
                        continue

        # If no detail URL, use the model's list/view URL with filter so the instance is focused
        if not instance_url:
            try:
                model_class = instance.__class__
                # Prefer settings menu entry (e.g. Department -> department_view) so we get
                # the correct list view even when there is no section in sub_section_menu
                instance_url = _get_model_list_view_url(model_class)
                if not instance_url:
                    section_info = get_section_info_for_model(model_class)
                    base_url = (section_info.get("url") or "").strip()
                    if base_url and base_url != "#":
                        section = section_info.get("section") or ""
                        if not base_url.startswith("/"):
                            parsed = urlparse(base_url)
                            base_url = parsed.path or base_url
                        instance_url = (
                            f"{base_url}?{urlencode({'section': section})}"
                            if section
                            else base_url
                        )
                # Append filter so the list view shows this instance (id=exact)
                if instance_url and getattr(instance, "pk", None) is not None:
                    filter_params = {
                        "apply_filter": "true",
                        "layout": "list",
                        "field": "id",
                        "operator": "exact",
                        "value": str(instance.pk),
                    }
                    sep = "&" if "?" in instance_url else "?"
                    instance_url = f"{instance_url}{sep}{urlencode(filter_params)}"
            except Exception as e:
                logger.debug(
                    "Could not get list/section URL for %s: %s",
                    instance.__class__.__name__,
                    str(e),
                )

        created_count = 0
        try:
            with transaction.atomic():
                for notification_user in users_to_notify:
                    try:

                        notification = create_notification(
                            user=notification_user,
                            message=notification_message,
                            sender=user,
                            url=instance_url,
                            instance=instance,
                            read=False,
                        )
                        if notification:
                            created_count += 1
                    except Exception as e:
                        logger.error(
                            "Error creating notification for user %s: %s",
                            notification_user.username,
                            str(e),
                            exc_info=True,
                        )
                        continue

            logger.info(
                "Created %s notifications for automation '%s' (instance: %s, URL: %s )",
                created_count,
                automation.title,
                instance,
                instance_url or "none",
            )
        except Exception as e:
            logger.error("Error creating notifications: %s", str(e), exc_info=True)

    except Exception as e:
        logger.error(
            "Error sending automation notification for %s: %s",
            automation.title,
            str(e),
            exc_info=True,
        )


def trigger_automations(instance, trigger_type="on_create", user=None):
    """
    Trigger all applicable automations for an instance.

    Args:
        instance: Model instance that triggered the automation
        trigger_type: Type of trigger ('on_create', 'on_update', 'on_delete')
        user: User who triggered the automation (optional)
    """
    try:
        content_type = HorillaContentType.objects.get_for_model(instance)

        # Get company from instance if it has one
        company = None
        if hasattr(instance, "company"):
            company = instance.company

        # If no company on instance, try to get from thread local request
        if not company:
            request = getattr(_thread_local, "request", None)
            if request:
                company = getattr(request, "active_company", None)

        # Build query filter
        # For 'on_create' or 'on_update', also include 'on_create_or_update' automations
        if trigger_type in ["on_create", "on_update"]:
            filter_kwargs = {
                "model": content_type,
                "trigger__in": [trigger_type, "on_create_or_update"],
                "is_active": True,  # Only active automations
            }
        else:
            filter_kwargs = {
                "model": content_type,
                "trigger": trigger_type,
                "is_active": True,  # Only active automations
            }

        # Filter by company if available
        if company:
            filter_kwargs["company"] = company

        automations = HorillaAutomation.objects.filter(**filter_kwargs)

        for automation in automations:
            try:
                execute_automation(automation, instance, user, trigger_type)
            except Exception as e:
                logger.error(
                    "Error executing automation %s: %s",
                    automation.title,
                    str(e),
                    exc_info=True,
                )
                continue

    except Exception as e:
        logger.error("Error triggering automations: %s", str(e), exc_info=True)
