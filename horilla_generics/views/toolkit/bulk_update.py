"""
Bulk update mixin extracted from HorillaListView to keep the main
list view class smaller and focused.
"""

# Standard library imports
import json
import logging
from datetime import datetime
from decimal import Decimal

# Third-party imports
from auditlog.models import LogEntry

# Third-party imports (Django)
from django.contrib import messages
from django.utils import timezone

from horilla.http import HttpResponse

# First-party imports (Horilla)
from horilla.shortcuts import render
from horilla_core.models import HorillaContentType
from horilla_core.utils import get_editable_fields

logger = logging.getLogger(__name__)


class HorillaBulkUpdateMixin:
    """
    Mixin that encapsulates all bulk update logic so that HorillaListView
    can delegate to it instead of implementing everything inline.
    """

    def handle_bulk_update_post(self, request, record_ids, columns):
        """
        Entry point from HorillaListView.post for bulk update paths.

        Returns an HttpResponse if a bulk update should be processed here,
        otherwise None (so the caller can continue its own logic).
        """
        # Bulk update modal via `bulk_update_form`
        if request.POST.get("bulk_update_form") == "true":
            selected_ids = request.POST.get("selected_ids", "[]")
            try:
                selected_ids = json.loads(selected_ids)
                selected_ids = [int(id) for id in selected_ids if str(id).isdigit()]
                valid_ids = (
                    self.get_queryset()
                    .filter(id__in=selected_ids)
                    .values_list("id", flat=True)
                )
                valid_ids = list(valid_ids)

                self.object_list = self.get_queryset()
                context = self.get_context_data()
                context["selected_ids"] = selected_ids
                context["selected_ids_json"] = json.dumps(selected_ids)
                return HorillaBulkUpdateMixin.render_bulk_update_form(
                    self, request, context
                )
            except (json.JSONDecodeError, ValueError) as e:
                logger.error("Error processing selected_ids: %s", str(e))
                self.object_list = self.get_queryset()
                context = self.get_context_data()
                context["selected_ids"] = []
                context["selected_ids_json"] = json.dumps([])
                return HorillaBulkUpdateMixin.render_bulk_update_form(
                    self, request, context
                )

        # Apply bulk update when `record_ids` is present and we have update values
        if record_ids:
            try:
                record_ids_list = json.loads(record_ids)
            except json.JSONDecodeError:
                return HttpResponse("Invalid JSON data for record_ids", status=400)

            editable_bulk_field_names = get_editable_fields(
                request.user, self.model, self.bulk_update_fields
            )
            bulk_updates = {}
            for field in editable_bulk_field_names:
                value = request.POST.get(f"bulk_update_value_{field}")
                if value:
                    bulk_updates[field] = value

            # Only handle as bulk update if at least one value was provided;
            # otherwise let the request fall through (e.g. to export or other handlers)
            if bulk_updates:
                return HorillaBulkUpdateMixin.handle_bulk_update(
                    self, record_ids_list, bulk_updates
                )

        # Legacy / simple bulk update (single field/value)
        if request.POST.get("bulk_update_field"):
            field_name = request.POST.get("bulk_update_field")
            new_value = request.POST.get("bulk_update_value")
            if record_ids and field_name and new_value:
                try:
                    record_ids_list = json.loads(record_ids)
                    return HorillaBulkUpdateMixin.handle_bulk_update(
                        self, record_ids_list, {field_name: new_value}
                    )
                except json.JSONDecodeError:
                    return HttpResponse("Invalid JSON data for record_ids", status=400)
            return HttpResponse("Invalid request: Missing required fields", status=400)

        return None

    def render_bulk_update_form(self, request, context):
        """Render the bulk update modal."""

        return render(request, "partials/bulk_update_form.html", context)

    def handle_bulk_update(self, record_ids, bulk_updates):
        """
        Perform and validate bulk updates for given record IDs.

        Coerces values according to field types and applies the updates; returns
        an HTTP response with error info on failure. Only fields with read+write
        permission are applied.
        """
        try:
            queryset = self.model.objects.filter(id__in=record_ids)
            # Use list view's field metadata when available (avoids cyclic import)
            if hasattr(self, "_get_model_fields"):
                field_infos = {
                    field["name"]: field for field in self._get_model_fields()
                }
            else:
                field_infos = {}

            editable_bulk_field_names = get_editable_fields(
                self.request.user, self.model, self.bulk_update_fields
            )
            editable_bulk_set = set(editable_bulk_field_names)

            update_dict = {}
            has_valid_values = False
            for field_name, new_value in bulk_updates.items():
                if field_name not in editable_bulk_set:
                    continue
                if new_value == "" or new_value is None:
                    continue

                field_info = field_infos.get(field_name)
                if not field_info:
                    return HttpResponse(f"Field {field_name} not found", status=400)

                field_type = field_info["type"]
                try:
                    if field_type == "boolean":
                        new_value = str(new_value).lower() in ("true", "yes", "1")
                    elif field_type in ("number", "integer"):
                        new_value = int(new_value)
                    elif field_type in ("float", "decimal"):
                        new_value = Decimal(new_value)
                    elif field_type in ("date", "datetime"):
                        fmt = "%Y-%m-%d" if field_type == "date" else "%Y-%m-%dT%H:%M"
                        new_value_dt = datetime.strptime(str(new_value), fmt)
                        if field_type == "date":
                            new_value = new_value_dt.date()
                        else:
                            new_value = new_value_dt
                    elif field_type == "choice":
                        choices = [c["value"] for c in field_info.get("choices", [])]
                        if new_value not in choices:
                            return HttpResponse(
                                f"Invalid choice for {field_name}", status=400
                            )
                    elif field_type == "foreignkey":
                        if new_value == "":
                            new_value = None
                        elif new_value:
                            try:
                                new_value = int(new_value)
                            except ValueError:
                                pass
                    update_dict[field_name] = new_value
                    has_valid_values = True
                except ValueError as e:
                    return HttpResponse(
                        f"Invalid value for field {field_name}: {str(e)}", status=400
                    )

            if not has_valid_values:
                messages.info(
                    self.request, "No fields were updated as no values were provided."
                )
                return HttpResponse(
                    f"<script>$('#reloadButton').click();$('#unselect-select-btn-{self.view_id}').click();</script>"
                )

            records_before = {obj.id: obj for obj in queryset}
            content_type = HorillaContentType.objects.get_for_model(self.model)
            user = self.request.user if self.request.user.is_authenticated else None

            updated_count = queryset.update(**update_dict)

            if updated_count > 0:
                for record_id in record_ids:
                    if record_id not in records_before:
                        continue
                    record = records_before[record_id]
                    updated_record = self.model.objects.get(id=record_id)

                    changes = {}
                    for field_name, _ in update_dict.items():
                        old_value = getattr(record, field_name, None)
                        new_value = getattr(updated_record, field_name, None)
                        if old_value != new_value:
                            changes[field_name] = [
                                str(old_value) if old_value is not None else "--",
                                str(new_value) if new_value is not None else "--",
                            ]

                    if changes:
                        LogEntry.objects.create(
                            content_type=content_type,
                            object_id=record_id,
                            object_repr=str(updated_record),
                            action=LogEntry.Action.UPDATE,
                            actor=user,
                            timestamp=timezone.now(),
                            changes=changes,
                        )

            messages.success(
                self.request, f"Updated {updated_count} records successfully."
            )

            self.object_list = self.get_queryset()
            return HttpResponse(
                f"<script>$('#reloadButton').click();$('#unselect-all-btn-{self.view_id}').click();</script>"
            )

        except Exception as e:
            return HttpResponse(f"Bulk update failed: {str(e)}", status=500)
