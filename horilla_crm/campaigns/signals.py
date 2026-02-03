"""Signal handlers for campaigns module."""

# Standard library imports
import logging

# Third-party imports (Django)
from django.db import transaction
from django.db.models import Sum
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

# First-party / Horilla imports
from horilla.auth.models import User
from horilla_core.signals import company_currency_changed
from horilla_crm.campaigns.models import Campaign, CampaignMember
from horilla_crm.leads.models import Lead
from horilla_crm.opportunities.models import Opportunity
from horilla_keys.models import ShortcutKey

logger = logging.getLogger(__name__)
# Define your campaigns signals here


@receiver(post_save, sender=User)
def create_campaign_shortcuts(sender, instance, created, **kwargs):
    """Create default keyboard shortcuts for campaigns when a user is created."""
    predefined = [
        {"page": "/campaigns/campaign-view/", "key": "C", "command": "alt"},
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


@receiver(company_currency_changed)
def update_campaigns_on_currency_change(sender, **kwargs):
    """
    Update Campaign currency amounts when a company's currency changes.
    """
    company = kwargs.get("company")
    conversion_rate = kwargs.get("conversion_rate")

    campaigns_to_update = []

    campaigns = Campaign.objects.filter(company=company).only(
        "id", "expected_revenue", "budget_cost", "actual_cost"
    )

    for campaign in campaigns:
        needs_update = False

        if campaign.expected_revenue is not None:
            campaign.expected_revenue *= conversion_rate
            needs_update = True

        if campaign.budget_cost is not None:
            campaign.budget_cost *= conversion_rate
            needs_update = True

        if campaign.actual_cost is not None:
            campaign.actual_cost *= conversion_rate
            needs_update = True

        if needs_update:
            campaigns_to_update.append(campaign)

    if campaigns_to_update:
        Campaign.objects.bulk_update(
            campaigns_to_update,
            ["expected_revenue", "budget_cost", "actual_cost"],
            batch_size=1000,
        )


def update_campaign_metrics(campaign):
    """
    Helper function to update campaign metrics.
    """
    try:
        with transaction.atomic():
            # Leads and converted leads
            campaign.leads_in_campaign = campaign.members.filter(
                member_type="lead"
            ).count()

            campaign.converted_leads_in_campaign = campaign.members.filter(
                member_type="lead", lead__is_convert=True
            ).count()

            # Contacts
            campaign.contacts_in_campaign = campaign.members.filter(
                member_type="contact"
            ).count()
            # Opportunities
            opportunities = campaign.opportunities.all()
            campaign.opportunities_in_campaign = opportunities.count()

            won_opps_by_final = opportunities.filter(stage__is_final=True)
            campaign.won_opportunities_in_campaign = won_opps_by_final.count()

            # Opportunity values
            value_opps = opportunities.aggregate(total=Sum("amount"))["total"] or 0

            value_won_opps = (
                opportunities.filter(stage__is_final=True).aggregate(
                    total=Sum("amount")
                )["total"]
                or 0
            )

            campaign.value_opportunities = value_opps
            campaign.value_won_opportunities = value_won_opps
            campaign.responses_in_campaign = campaign.members.filter(
                member_status="responded"
            ).count()

            campaign.save(
                update_fields=[
                    "leads_in_campaign",
                    "converted_leads_in_campaign",
                    "contacts_in_campaign",
                    "opportunities_in_campaign",
                    "won_opportunities_in_campaign",
                    "value_opportunities",
                    "value_won_opportunities",
                    "responses_in_campaign",
                ]
            )
    except Exception as e:
        logger.error("Error updating campaign metrics for %s: %s", campaign, e)


@receiver([post_save, post_delete], sender=CampaignMember)
def update_campaign_on_member_change(sender, instance, **kwargs):
    """
    Update campaign metrics when a CampaignMember is created, updated, or deleted.
    """
    campaign = instance.campaign
    update_campaign_metrics(campaign)


@receiver(post_save, sender=Opportunity)
def update_campaign_on_opportunity_change(sender, instance, **kwargs):
    """
    Update campaign metrics when an Opportunity is created or updated.
    Handles changes to primary_campaign_source, stage, and amount.
    """
    try:
        # Get the previous state of the Opportunity (if updating)
        previous_campaign = None
        previous_stage_type = None
        previous_amount = None
        if not kwargs.get("created"):  # Update, not creation
            try:
                previous = Opportunity.objects.get(pk=instance.pk)
                previous_campaign = previous.primary_campaign_source
                previous_stage_type = (
                    previous.stage.stage_type if previous.stage else None
                )
                previous_amount = previous.amount
            except Opportunity.DoesNotExist:
                logger.warning("Previous Opportunity %s not found", instance.pk)

        if instance.primary_campaign_source:
            update_campaign_metrics(instance.primary_campaign_source)

        if previous_campaign and previous_campaign != instance.primary_campaign_source:
            update_campaign_metrics(previous_campaign)

        current_stage_type = instance.stage.stage_type if instance.stage else None
        if not kwargs.get("created") and (
            previous_stage_type != current_stage_type
            or previous_amount != instance.amount
        ):
            if instance.primary_campaign_source:
                logger.debug(
                    "Stage or amount changed for Opportunity %s: "
                    "stage_type=%s, amount=%s",
                    instance.pk,
                    current_stage_type,
                    instance.amount,
                )
                update_campaign_metrics(instance.primary_campaign_source)

    except Exception as e:
        logger.error(
            "Error in update_campaign_on_opportunity_change for Opportunity %s: %s",
            instance.pk,
            e,
        )


@receiver(post_delete, sender=Opportunity)
def update_campaign_on_opportunity_delete(sender, instance, **kwargs):
    """
    Update campaign metrics when an Opportunity is deleted.
    """
    if instance.primary_campaign_source:
        update_campaign_metrics(instance.primary_campaign_source)


@receiver(post_save, sender=Lead)
def update_campaign_on_lead_conversion(sender, instance, **kwargs):
    """Update campaign metrics when a lead is converted."""
    if instance.is_convert and kwargs.get("created"):
        campaign_members = CampaignMember.objects.filter(lead=instance)
        for member in campaign_members:
            update_campaign_metrics(member.campaign)
    elif not kwargs.get("created"):
        try:
            old_instance = Lead.objects.get(pk=instance.pk)
            if not old_instance.is_convert and instance.is_convert:
                campaign_members = CampaignMember.objects.filter(lead=instance)
                for member in campaign_members:
                    update_campaign_metrics(member.campaign)
        except Lead.DoesNotExist:
            pass
