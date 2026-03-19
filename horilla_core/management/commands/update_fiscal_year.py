"""
Horilla management command to update fiscal year instances.

This module provides a management command that checks the current status of
fiscal years and automatically updates them (e.g., marking expired ones as
inactive) and creates the next fiscal year if needed.
"""

# Third-party imports (Django)
from django.core.management.base import BaseCommand

# First-party / Horilla imports
from horilla_core.services.fiscal_year_service import FiscalYearService


class Command(BaseCommand):
    """
    Django management command to update fiscal year instances.

    This command checks the current status of fiscal years and automatically
    updates them (e.g., marking expired ones as inactive) and creates the
    next fiscal year if needed.
    """

    help = "Updates fiscal year instances by checking current status and creating next fiscal year"

    def handle(self, *args, **kwargs):
        # Use the service method to check and update all fiscal years
        results = FiscalYearService.check_and_update_fiscal_years()

        # Report results
        if results["updated"]:
            for fy in results["updated"]:
                self.stdout.write(
                    self.style.SUCCESS(f"Updated current fiscal year to {fy}")
                )

        if results["created"]:
            for fy in results["created"]:
                self.stdout.write(
                    self.style.SUCCESS(f"Created new fiscal year: {fy.name}")
                )

        if not results["updated"] and not results["created"]:
            self.stdout.write(self.style.SUCCESS("All fiscal years are up to date"))
