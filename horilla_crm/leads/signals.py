"""
Signal handlers for leads in Horilla CRM.
Handles automatic updates when company-related events occur, e.g., currency change.
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import transaction
from django.db.models import Case, F, IntegerField, Q, When
from django.db.models.signals import post_save, pre_delete
from django.dispatch import Signal, receiver
from django.http import HttpResponse
from django.urls import reverse_lazy

# First-party / Horilla imports
from horilla.auth.models import User
from horilla_core.signals import company_created, company_currency_changed
from horilla_crm.leads.models import (
    Lead,
    ScoringCondition,
    ScoringCriterion,
    ScoringRule,
)
from horilla_keys.models import ShortcutKey

logger = logging.getLogger(__name__)


lead_stage_created = Signal()


@receiver(company_created)
def handle_company_created(sender, instance, request, view, is_new, **kwargs):
    """Inject lead stages loading after company creation"""
    if is_new:  # Only for new companies
        url = reverse_lazy("leads:load_lead_stages", kwargs={"company_id": instance.id})
        return HttpResponse(
            f"""
            <script>
                closeModal();
                $('#reloadButton').click();
                openContentModal();
                var div = document.createElement('div');
                div.setAttribute('hx-get', '{url}');
                div.setAttribute('hx-target', '#contentModalBox');
                div.setAttribute('hx-trigger', 'load');
                div.setAttribute('hx-swap', 'innerHTML');
                document.body.appendChild(div);
                htmx.process(div);
            </script>
            """,
            headers={"X-Debug": "Modal transition in progress"},
        )
    return None


@receiver(company_currency_changed)
def update_crm_on_currency_change(sender, **kwargs):
    """
    Updates Lead amounts when a company's currency changes.
    """
    company = kwargs.get("company")
    conversion_rate = kwargs.get("conversion_rate")

    leads_to_update = []
    leads = (
        Lead.objects.filter(company=company)
        .select_related()
        .only("id", "annual_revenue")
    )

    for lead in leads:
        if lead.annual_revenue is not None:
            lead.annual_revenue = lead.annual_revenue * conversion_rate
            leads_to_update.append(lead)

    if leads_to_update:
        Lead.objects.bulk_update(leads_to_update, ["annual_revenue"], batch_size=1000)


@receiver(post_save, sender=User)
def create_leads_shortcuts(sender, instance, created, **kwargs):
    """Create default keyboard shortcuts for leads when a user is created."""
    predefined = [
        {"page": "/leads/leads-view/", "key": "E", "command": "alt"},
    ]

    for item in predefined:
        ShortcutKey.all_objects.get_or_create(
            user=instance,
            key=item["key"],
            command=item["command"],
            defaults={
                "page": item["page"],
                "company": instance.company,
            },
        )


def get_score_field(model):
    """Get the score field name for a given model."""
    score_fields = {
        "lead": "lead_score",
        "opportunity": "opportunity_score",
        "account": "account_score",
        "contact": "contact_score",
    }
    return score_fields.get(model._meta.model_name)


def get_models_for_module(module):
    """
    Dynamically find models matching a module name (e.g., 'lead') across installed apps.
    Only includes models that have a corresponding score field.
    """
    models = []
    for app_config in apps.get_app_configs():
        for model in app_config.get_models():
            if model._meta.model_name == module:
                score_field = get_score_field(model)
                if score_field and score_field in [f.name for f in model._meta.fields]:
                    models.append(model)
    return models


def build_query_from_conditions(criterion, Model):
    """
    Build a Django ORM query to filter instances that match a criterion's conditions.

    Args:
        criterion: ScoringCriterion instance.
        Model: The Django model class (e.g., Lead).

    Returns:
        Q object representing the combined conditions.
    """
    query = Q()
    for condition in criterion.conditions.all().order_by("order"):
        field = condition.field
        operator = condition.operator
        value = condition.value
        logical_operator = condition.logical_operator

        try:
            Model._meta.get_field(field)
            if operator == "equals":
                if Model._meta.get_field(field).get_internal_type() == "ForeignKey":
                    condition_query = Q(**{f"{field}_id__exact": value})
                else:
                    condition_query = Q(**{f"{field}__exact": value})
            elif operator == "not_equals":
                if Model._meta.get_field(field).get_internal_type() == "ForeignKey":
                    condition_query = ~Q(**{f"{field}_id__exact": value})
                else:
                    condition_query = ~Q(**{f"{field}__exact": value})
            elif operator == "contains":
                condition_query = Q(**{f"{field}__icontains": value})
            elif operator == "not_contains":
                condition_query = ~Q(**{f"{field}__icontains": value})
            elif operator == "starts_with":
                condition_query = Q(**{f"{field}__istartswith": value})
            elif operator == "ends_with":
                condition_query = Q(**{f"{field}__iendswith": value})
            elif operator == "greater_than":
                try:
                    condition_query = Q(**{f"{field}__gt": float(value)})
                except (ValueError, TypeError):
                    condition_query = Q(pk__in=[])
            elif operator == "greater_than_equal":
                try:
                    condition_query = Q(**{f"{field}__gte": float(value)})
                except (ValueError, TypeError):
                    condition_query = Q(pk__in=[])
            elif operator == "less_than":
                try:
                    condition_query = Q(**{f"{field}__lt": float(value)})
                except (ValueError, TypeError):
                    condition_query = Q(pk__in=[])
            elif operator == "less_than_equal":
                try:
                    condition_query = Q(**{f"{field}__lte": float(value)})
                except (ValueError, TypeError):
                    condition_query = Q(pk__in=[])
            elif operator == "is_empty":
                condition_query = Q(**{field: None}) | Q(**{f"{field}__exact": ""})
            elif operator == "is_not_empty":
                condition_query = ~Q(**{field: None}) & ~Q(**{f"{field}__exact": ""})
            else:
                condition_query = Q(pk__in=[])
            if logical_operator == "and":
                query &= condition_query
            else:
                query |= condition_query
        except FieldDoesNotExist:
            logger.warning(
                "Field %s does not exist on %s", field, Model._meta.model_name
            )
            query &= Q(pk__in=[])

    return query


def update_all_scores_for_module(module):
    """
    Update score fields for instances matching active scoring rules' conditions
    using direct database UPDATE queries.

    Args:
        module: String (e.g., 'lead', 'opportunity') indicating the module.
    """
    models = get_models_for_module(module)
    for Model in models:
        score_field = get_score_field(Model)
        if not score_field:
            continue

        with transaction.atomic():
            try:
                Model.objects.update(**{score_field: 0})
                logger.info(
                    "Reset %s to 0 for all %s instances",
                    score_field,
                    Model._meta.model_name,
                )
            except Exception as e:
                logger.error(
                    "Error resetting %s for %s: %s",
                    score_field,
                    Model._meta.model_name,
                    e,
                )
                raise

            rules = ScoringRule.objects.filter(module=module, is_active=True)
            if not rules.exists():
                continue

            for rule in rules:
                for criterion in rule.criteria.all().order_by("order"):
                    query = build_query_from_conditions(criterion, Model)
                    if not query:
                        continue

                    points = criterion.points
                    if criterion.operation_type == "sub":
                        points = -points

                    try:
                        Model.objects.filter(query).update(
                            **{
                                score_field: Case(
                                    When(query, then=F(score_field) + points),
                                    default=F(score_field),
                                    output_field=IntegerField(),
                                )
                            }
                        )
                        logger.info(
                            "Updated %s for %s instances matching criterion %s",
                            score_field,
                            Model._meta.model_name,
                            criterion.id,
                        )
                    except Exception as e:
                        logger.error(
                            "Error updating %s for %s with criterion %s: %s",
                            score_field,
                            Model._meta.model_name,
                            criterion.id,
                            e,
                        )
                        raise


@receiver(post_save, sender=ScoringRule)
@receiver(pre_delete, sender=ScoringRule)
def handle_rule_change(sender, instance, **kwargs):
    """
    Signal handler triggered when a scoring rule is created, updated, or deleted.
    Automatically triggers recalculation of all scores for the associated module.
    """
    update_all_scores_for_module(instance.module)


@receiver(post_save, sender=ScoringCriterion)
@receiver(pre_delete, sender=ScoringCriterion)
def handle_criterion_change(sender, instance, **kwargs):
    """
    Signal handler triggered when a scoring criterion is created, updated, or deleted.
    Ensures scores are recalculated for all modules affected by this criterion.
    """
    update_all_scores_for_module(instance.rule.module)


@receiver(post_save, sender=ScoringCondition)
@receiver(pre_delete, sender=ScoringCondition)
def handle_condition_change(sender, instance, **kwargs):
    """
    Signal handler triggered when a scoring condition is created, updated, or deleted.
    Rebuilds and applies scoring rules to update scores for affected module instances.
    """
    update_all_scores_for_module(instance.criterion.rule.module)
