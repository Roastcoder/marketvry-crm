"""
This module contains signal handlers and utility functions for Horilla's core
models such as Company, FiscalYear, MultipleCurrency, and related
models.

Features implemented in this module include:
- Automatic fiscal year configuration when a company is created or updated.
- Default currency initialization and handling of multi-currency configurations.
- Custom permission creation during migrations.
- Helper utilities to dynamically discover models and build filter queries.

"""

import logging
from decimal import Decimal

from django.apps import apps
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_delete, post_migrate, post_save
from django.dispatch import Signal, receiver

from horilla.auth.models import User
from horilla_core.models import (
    Company,
    FieldPermission,
    FiscalYear,
    ListColumnVisibility,
    MultipleCurrency,
    Role,
)
from horilla_core.services.fiscal_year_service import FiscalYearService
from horilla_core.utils import get_user_field_permission

logger = logging.getLogger(__name__)


company_currency_changed = Signal()
company_created = Signal()
pre_logout_signal = Signal()
pre_login_render_signal = Signal()


@receiver(post_save, sender="horilla_core.Company")
def create_company_fiscal_config(sender, instance, created, **kwargs):
    """
    Handle fiscal year configuration when a company is created
    """
    if created:
        try:
            config = FiscalYear.objects.get(company=instance)
        except FiscalYear.DoesNotExist:
            config = FiscalYearService.get_or_create_company_configuration(instance)

        # Generate fiscal years for this config
        FiscalYearService.generate_fiscal_years(config)


@receiver(post_save, sender="horilla_core.FiscalYear")
def generate_fiscal_years_on_config_save(sender, instance, created, **kwargs):
    """
    Generate fiscal years when configuration is saved.
    Uses transaction.on_commit to avoid database locking issues.
    """
    if not created and instance.company:  # Only run on updates, not creation
        transaction.on_commit(lambda: FiscalYearService.generate_fiscal_years(instance))


@receiver(post_save, sender=Company)
def create_default_currency(sender, instance, created, **kwargs):
    """
    Create default currency for new companies and update conversion rates.
    """
    if created and instance.currency:
        try:
            with transaction.atomic():
                if not MultipleCurrency.objects.filter(
                    company=instance, currency=instance.currency
                ).exists():
                    new_currency = MultipleCurrency.objects.create(
                        company=instance,
                        currency=instance.currency,
                        is_default=True,
                        conversion_rate=Decimal("1.00"),
                        decimal_places=2,
                        format="western_format",
                        created_at=instance.created_at,
                        updated_at=instance.updated_at,
                        created_by=instance.created_by,
                        updated_by=instance.updated_by,
                    )
                    all_currencies = MultipleCurrency.objects.filter(
                        company=instance
                    ).exclude(pk=new_currency.pk)
                    if all_currencies.exists():
                        for curr in all_currencies:
                            curr.is_default = False
                            curr.save()
        except Exception as e:
            logger.error(
                "Error creating default currency for company %s: %s",
                instance.id,
                e,
            )


def add_custom_permissions(sender, **kwargs):
    """
    Add custom permissions for models
    that define default Django permissions.
    """
    for model in apps.get_models():
        opts = model._meta

        # Skip models that don't use default permissions
        if opts.default_permissions == ():
            continue

        content_type = ContentType.objects.get_for_model(model)

        add_view_own = (
            "view_own" in opts.default_permissions
            or opts.default_permissions == ("add", "change", "delete", "view")
        )

        add_change_own = (
            "change_own" in opts.default_permissions
            or opts.default_permissions == ("add", "change", "delete", "view")
        )

        add_create_own = (
            "create_own" in opts.default_permissions
            or opts.default_permissions == ("add", "change", "delete", "view")
        )

        add_delete_own = (
            "delete_own" in opts.default_permissions
            or opts.default_permissions == ("add", "change", "delete", "view")
        )

        custom_perms = []

        if add_view_own:
            custom_perms.append(("view_own", f"Can view own {opts.verbose_name_raw}"))

        if add_change_own:
            custom_perms.append(
                ("change_own", f"Can change own {opts.verbose_name_raw}")
            )

        if add_create_own:
            custom_perms.append(("add_own", f"Can create own {opts.verbose_name_raw}"))

        if add_delete_own:
            custom_perms.append(
                ("delete_own", f"Can delete own {opts.verbose_name_raw}")
            )

        for code_prefix, name in custom_perms:
            codename = f"{code_prefix}_{opts.model_name}"
            if not Permission.objects.filter(
                codename=codename, content_type=content_type
            ).exists():
                Permission.objects.create(
                    codename=codename,
                    name=name,
                    content_type=content_type,
                )


post_migrate.connect(add_custom_permissions)


@receiver(post_save, sender=User)
def ensure_view_own_permissions(sender, instance, created, **kwargs):
    """
    Assign view_own permissions to newly created non-superuser users.
    """
    if not created or instance.is_superuser:
        return

    def assign_permissions():
        try:
            view_own_perms = Permission.objects.filter(codename__startswith="view_own_")
            if view_own_perms.exists():
                instance.user_permissions.add(*view_own_perms)
        except Exception as e:
            print(f"✗ Error assigning permissions to {instance.username}: {e}")

    transaction.on_commit(assign_permissions)


@receiver(post_save, sender=Role)
def ensure_role_view_own_permissions(sender, instance, created, **kwargs):
    """
    Assign view_own permissions to newly created or updated roles.
    Also assign these permissions to all members of the role.
    """

    def assign_permissions():
        try:
            view_own_perms = Permission.objects.filter(codename__startswith="view_own_")

            if not view_own_perms.exists():
                print(f"✗ No view_own permissions found")
                return

            existing_perm_ids = set(instance.permissions.values_list("id", flat=True))

            view_own_perm_ids = set(view_own_perms.values_list("id", flat=True))

            missing_perm_ids = view_own_perm_ids - existing_perm_ids

            if missing_perm_ids:
                missing_perms = Permission.objects.filter(id__in=missing_perm_ids)

                instance.permissions.add(*missing_perms)

                members = instance.users.all()
                for member in members:
                    member.user_permissions.add(*missing_perms)

                if created:
                    print(
                        f"✓ Assigned {len(missing_perm_ids)} view_own permissions to new role '{instance.role_name}'"
                    )
                else:
                    print(
                        f"✓ Updated {len(missing_perm_ids)} view_own permissions for role '{instance.role_name}'"
                    )

                if members.exists():
                    print(
                        f"  ✓ Updated {members.count()} members of role '{instance.role_name}'"
                    )

        except Exception as e:
            print(f"✗ Error assigning permissions to role '{instance.role_name}': {e}")

    transaction.on_commit(assign_permissions)


@receiver(post_save, sender=User)
def user_default_field_permissions(sender, instance, created, **kwargs):
    """
    Assign default field permissions to newly created users.
    """
    if not created or instance.is_superuser:
        return

    def assign_permissions():
        try:
            for model in apps.get_models():
                defaults = getattr(model, "default_field_permissions", {})
                if not defaults:
                    continue

                content_type = ContentType.objects.get_for_model(model)
                for field_name, perm in defaults.items():
                    FieldPermission.objects.get_or_create(
                        user=instance,
                        content_type=content_type,
                        field_name=field_name,
                        defaults={"permission_type": perm},
                    )
        except Exception as e:
            print(
                f"✗ Error assigning default field permissions to {instance.username}: {e}"
            )

    transaction.on_commit(assign_permissions)


@receiver(post_save, sender=Role)
def role_default_field_permissions(sender, instance, created, **kwargs):
    """
    Assign default field permissions to newly created roles.
    Also assign these permissions to all members of the role.
    """

    def assign_permissions():
        try:
            for model in apps.get_models():
                defaults = getattr(model, "default_field_permissions", {})
                if not defaults:
                    continue

                content_type = ContentType.objects.get_for_model(model)

                for field_name, perm in defaults.items():
                    # Assign to role
                    FieldPermission.objects.get_or_create(
                        role=instance,
                        content_type=content_type,
                        field_name=field_name,
                        defaults={"permission_type": perm},
                    )

                    # Assign to all users in this role
                    for user in instance.users.all():
                        FieldPermission.objects.get_or_create(
                            user=user,
                            content_type=content_type,
                            field_name=field_name,
                            defaults={"permission_type": perm},
                        )

        except Exception as e:
            print(
                f"✗ Error assigning default field permissions to role '{instance.role_name}': {e}"
            )

    transaction.on_commit(assign_permissions)


@receiver(post_save, sender=FieldPermission)
@receiver(post_delete, sender=FieldPermission)
def clear_column_visibility_cache_on_permission_change(sender, instance, **kwargs):
    """
    Clear column visibility cache and clean up ListColumnVisibility records
    when field permissions are created, updated, or deleted.
    This ensures that list/kanban views reflect permission changes immediately.
    """

    def cleanup_visibility_records():
        try:

            content_type = instance.content_type
            app_label = content_type.app_label
            field_name = instance.field_name

            # Get the model class - use model_name from content_type first, then get class name
            try:
                model = content_type.model_class()
                if not model:
                    # Fallback: try to get model using content_type.model (lowercase)
                    model = apps.get_model(
                        app_label=app_label, model_name=content_type.model
                    )
                model_name = (
                    model.__name__
                )  # Use class name (capitalized) as stored in ListColumnVisibility
            except (LookupError, AttributeError) as e:
                logger.error(
                    "Model not found: %s.%s: %s",
                    app_label,
                    content_type.model,
                    e,
                )
                return

            # Determine affected users
            affected_users = []
            if instance.user:
                affected_users = [instance.user]
            elif instance.role:
                affected_users = list(instance.role.users.all())

            # Get the permission type (if it's a save, check the new permission; if delete, field is now visible)
            _permission_type = None
            if hasattr(instance, "permission_type"):
                _permission_type = instance.permission_type

            # Process each affected user
            for user in affected_users:
                # Get all ListColumnVisibility entries for this user and model
                # Try both model_name formats (class name and lowercase) to be safe
                visibility_entries = ListColumnVisibility.all_objects.filter(
                    user=user, app_label=app_label
                ).filter(Q(model_name=model_name) | Q(model_name=model_name.lower()))
                for entry in visibility_entries:
                    updated = False

                    # Check current permission for this user and field
                    current_permission = get_user_field_permission(
                        user, model, field_name
                    )

                    # If field is now hidden, remove it from visible_fields and removed_custom_fields
                    if current_permission == "hidden":
                        # Remove from visible_fields
                        original_visible_fields = (
                            entry.visible_fields.copy() if entry.visible_fields else []
                        )
                        updated_visible_fields = []

                        for field_item in original_visible_fields:
                            # Handle both [verbose_name, field_name] and field_name formats
                            if (
                                isinstance(field_item, (list, tuple))
                                and len(field_item) >= 2
                            ):
                                item_field_name = field_item[1]
                            else:
                                item_field_name = field_item

                            # Check if this field matches the hidden field
                            # Handle both direct field name and display method (get_*_display)
                            field_matches = (
                                item_field_name == field_name
                                or item_field_name == f"get_{field_name}_display"
                                or (
                                    item_field_name.startswith("get_")
                                    and item_field_name.endswith("_display")
                                    and item_field_name.replace("get_", "").replace(
                                        "_display", ""
                                    )
                                    == field_name
                                )
                            )

                            if not field_matches:
                                updated_visible_fields.append(field_item)
                            else:
                                updated = True

                        # Remove from removed_custom_fields
                        original_removed_fields = (
                            entry.removed_custom_fields.copy()
                            if entry.removed_custom_fields
                            else []
                        )
                        updated_removed_fields = []

                        for field_item in original_removed_fields:
                            if (
                                isinstance(field_item, (list, tuple))
                                and len(field_item) >= 2
                            ):
                                item_field_name = field_item[1]
                            else:
                                item_field_name = field_item

                            # Check if this field matches the hidden field
                            field_matches = (
                                item_field_name == field_name
                                or item_field_name == f"get_{field_name}_display"
                                or (
                                    item_field_name.startswith("get_")
                                    and item_field_name.endswith("_display")
                                    and item_field_name.replace("get_", "").replace(
                                        "_display", ""
                                    )
                                    == field_name
                                )
                            )

                            if not field_matches:
                                updated_removed_fields.append(field_item)
                            else:
                                updated = True

                        # Update the entry if changes were made
                        if updated:
                            entry.visible_fields = updated_visible_fields
                            entry.removed_custom_fields = updated_removed_fields
                            entry.save(
                                update_fields=[
                                    "visible_fields",
                                    "removed_custom_fields",
                                ]
                            )

                    # If field is now visible (not hidden), ensure it's available and re-add if it was previously visible
                    elif current_permission != "hidden":

                        # Get the model's default fields to check if this is a standard field
                        try:
                            from django.db.models import Field as ModelField
                            from django.utils.encoding import force_str

                            model_instance = model()
                            model_fields = [
                                [
                                    force_str(f.verbose_name or f.name.title()),
                                    (
                                        f.name
                                        if not getattr(f, "choices", None)
                                        else f"get_{f.name}_display"
                                    ),
                                ]
                                for f in model._meta.get_fields()
                                if isinstance(f, ModelField)
                                and f.name not in ["history"]
                            ]

                            # Check if model has a columns property
                            default_fields = (
                                getattr(model_instance, "columns", model_fields)
                                if hasattr(model_instance, "columns")
                                else model_fields
                            )

                            # Find the field in default fields (check both field_name and get_*_display)
                            field_to_add = None
                            for default_field in default_fields:
                                if (
                                    isinstance(default_field, (list, tuple))
                                    and len(default_field) >= 2
                                ):
                                    default_field_name = default_field[1]
                                    default_verbose_name = default_field[0]

                                    # Check if this default field matches our field
                                    field_matches = (
                                        default_field_name == field_name
                                        or default_field_name
                                        == f"get_{field_name}_display"
                                        or (
                                            default_field_name.startswith("get_")
                                            and default_field_name.endswith("_display")
                                            and default_field_name.replace(
                                                "get_", ""
                                            ).replace("_display", "")
                                            == field_name
                                        )
                                    )

                                    if field_matches:
                                        field_to_add = [
                                            default_verbose_name,
                                            default_field_name,
                                        ]
                                        break

                            # If field is in default fields and not in visible_fields, add it back
                            if field_to_add:
                                current_visible_fields = (
                                    entry.visible_fields.copy()
                                    if entry.visible_fields
                                    else []
                                )
                                field_already_in_visible = any(
                                    (
                                        isinstance(item, (list, tuple))
                                        and len(item) >= 2
                                        and item[1] == field_to_add[1]
                                    )
                                    or (
                                        not isinstance(item, (list, tuple))
                                        and item == field_to_add[1]
                                    )
                                    for item in current_visible_fields
                                )

                                if not field_already_in_visible:
                                    current_visible_fields.append(field_to_add)
                                    entry.visible_fields = current_visible_fields
                                    updated = True

                            # Remove from removed_custom_fields if it's there
                            original_removed_fields = (
                                entry.removed_custom_fields.copy()
                                if entry.removed_custom_fields
                                else []
                            )
                            updated_removed_fields = []

                            for field_item in original_removed_fields:
                                if (
                                    isinstance(field_item, (list, tuple))
                                    and len(field_item) >= 2
                                ):
                                    item_field_name = field_item[1]
                                else:
                                    item_field_name = field_item

                                # Check if this field matches the now-visible field
                                field_matches = (
                                    item_field_name == field_name
                                    or item_field_name == f"get_{field_name}_display"
                                    or (
                                        item_field_name.startswith("get_")
                                        and item_field_name.endswith("_display")
                                        and item_field_name.replace("get_", "").replace(
                                            "_display", ""
                                        )
                                        == field_name
                                    )
                                )

                                if not field_matches:
                                    updated_removed_fields.append(field_item)
                                else:
                                    updated = True

                            if updated:
                                entry.removed_custom_fields = updated_removed_fields
                                entry.save(
                                    update_fields=[
                                        "visible_fields",
                                        "removed_custom_fields",
                                    ]
                                )
                        except Exception as e:
                            logger.error(
                                "Error checking default fields for re-adding: %s",
                                e,
                            )

                    # Clear cache for this entry
                    cache_key = f"visible_columns_{entry.user.id}_{entry.app_label}_{entry.model_name}_{entry.context}_{entry.url_name}"
                    cache.delete(cache_key)

        except Exception as e:
            logger.error(
                "Error cleaning up column visibility records on permission change: %s",
                e,
            )

    transaction.on_commit(cleanup_visibility_records)


def clear_list_column_cache_for_model(content_type, affected_users=None):
    """
    Clear list column visibility cache for all users who have ListColumnVisibility
    for the given model (content_type).

    Args:
        content_type: ContentType instance for the model
        affected_users: Optional list of user IDs to limit cache clearing to specific users
    """
    try:

        app_label = content_type.app_label
        model_name = (
            content_type.model_class().__name__ if content_type.model_class() else None
        )

        if not model_name:
            return

        # Get all ListColumnVisibility records for this model
        visibility_queryset = ListColumnVisibility.all_objects.filter(
            app_label=app_label, model_name=model_name
        )

        # If specific users are provided, filter to those users
        if affected_users:
            visibility_queryset = visibility_queryset.filter(user_id__in=affected_users)

        # Clear cache for each visibility record
        for visibility in visibility_queryset:
            cache_key = f"visible_columns_{visibility.user.id}_{app_label}_{model_name}_{visibility.context}_{visibility.url_name}"
            cache.delete(cache_key)

    except Exception as e:
        logger.error("Error clearing list column cache: %s", e)


@receiver(post_save, sender=Company)
def assign_first_company_to_all_users(sender, instance, created, **kwargs):
    """Assign the first company created to all users"""
    if created:
        if Company.objects.count() == 1:
            User.objects.filter(company__isnull=True).update(company=instance)
