"""Helper methods for ForecastTypeTabView (create forecasts, trends, enhance data)."""

# First-party / Horilla imports
from horilla.auth.models import User
from horilla.utils.translation import gettext_lazy as _
from horilla_core.models import Period
from horilla_crm.forecast.models import Forecast


class ForecastTypeTabHelpersMixin:
    """Mixin with create_* and trend/enhance helpers for ForecastTypeTabView."""

    def create_empty_user_forecast_with_owner(
        self, period, forecast_type, user_id, currency_symbol, target=None
    ):
        """
        Create a placeholder forecast for a user
        with no data - returns actual forecast object.
        """
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None

        # Create an actual Forecast object (not saved to DB) with proper attributes
        forecast = Forecast()
        forecast.id = f"empty_{period.id}_{user_id}"
        forecast.period = period
        forecast.quarter = period.quarter
        forecast.fiscal_year = period.quarter.fiscal_year
        forecast.forecast_type = forecast_type
        forecast.owner = user
        forecast.owner_id = user.id  # Ensure owner_id is set

        # Set target and other fields based on forecast type
        if target and forecast_type.is_quantity_based:
            forecast.target_quantity = target.target_amount
            forecast.pipeline_quantity = 0
            forecast.best_case_quantity = 0
            forecast.commit_quantity = 0
            forecast.closed_quantity = 0
            forecast.actual_quantity = 0
            forecast.gap_quantity = forecast.target_quantity
        elif target:
            forecast.target_amount = target.target_amount
            forecast.pipeline_amount = 0
            forecast.best_case_amount = 0
            forecast.commit_amount = 0
            forecast.closed_amount = 0
            forecast.actual_amount = 0
            forecast.gap_amount = forecast.target_amount
        else:
            if forecast_type.is_quantity_based:
                forecast.target_quantity = 0
                forecast.pipeline_quantity = 0
                forecast.best_case_quantity = 0
                forecast.commit_quantity = 0
                forecast.closed_quantity = 0
                forecast.actual_quantity = 0
                forecast.gap_quantity = 0
            else:
                forecast.target_amount = 0
                forecast.pipeline_amount = 0
                forecast.best_case_amount = 0
                forecast.commit_amount = 0
                forecast.closed_amount = 0
                forecast.actual_amount = 0
                forecast.gap_amount = 0

        forecast.performance_percentage = 0
        forecast.gap_percentage = 0
        forecast.closed_percentage = 0
        forecast.closed_deals_count = 0
        forecast.currency_symbol = currency_symbol

        return forecast

    def extract_target_from_bulk(self, targets_data, period, user_id):
        """Helper to extract target from bulk loaded data"""
        if user_id:
            target = targets_data.get(period.id)
            if target:
                return target
            return None

        period_targets = targets_data.get(period.id, [])
        total_target = sum(target.target_amount for target in period_targets)

        if total_target > 0:

            class AggregatedTarget:
                """Wrapper for summed target amounts from multiple period targets."""

                def __init__(self, target_amount):
                    self.target_amount = target_amount

            return AggregatedTarget(total_target)
        return None

    def calculate_trend_direction(self, current, previous):
        """Helper to calculate trend direction"""
        if current > previous:
            return "up"
        if current < previous:
            return "down"
        return None

    def format_change_text(
        self, current, previous, period_name, is_quantity_based, currency
    ):
        """Helper to format change text"""
        if current == previous:
            return f"No change from {period_name}"

        change = abs(current - previous)
        direction = "increased" if current > previous else "decreased"
        unit = "deals" if is_quantity_based else currency or "USD"

        return (
            f"{direction.title()} by {change} {unit} from {period_name}"
            if is_quantity_based
            else f"{direction.title()} by {change:,.0f} {unit} from {period_name}"
        )

    def get_user_specific_trend_data(
        self, user_id, period_id, previous_period_id, user_period_data, forecast_type
    ):
        """
        Calculate trend data for a specific user between two periods
        """
        user_data = user_period_data.get(user_id, {})
        current_data = user_data.get(
            period_id, {"commit": 0, "best_case": 0, "pipeline": 0, "closed": 0}
        )
        previous_data = user_data.get(
            previous_period_id,
            {"commit": 0, "best_case": 0, "pipeline": 0, "closed": 0},
        )

        # Get the previous period name for change text
        previous_period = Period.objects.get(id=previous_period_id)

        return {
            "commit_trend": self.calculate_trend_direction(
                current_data["commit"], previous_data["commit"]
            ),
            "best_case_trend": self.calculate_trend_direction(
                current_data["best_case"], previous_data["best_case"]
            ),
            "pipeline_trend": self.calculate_trend_direction(
                current_data["pipeline"], previous_data["pipeline"]
            ),
            "closed_trend": self.calculate_trend_direction(
                current_data["closed"], previous_data["closed"]
            ),
            "commit_change_text": self.format_change_text(
                current_data["commit"],
                previous_data["commit"],
                previous_period.name,
                forecast_type.is_quantity_based,
                self.get_company_for_user.currency,
            ),
            "best_case_change_text": self.format_change_text(
                current_data["best_case"],
                previous_data["best_case"],
                previous_period.name,
                forecast_type.is_quantity_based,
                self.get_company_for_user.currency,
            ),
            "pipeline_change_text": self.format_change_text(
                current_data["pipeline"],
                previous_data["pipeline"],
                previous_period.name,
                forecast_type.is_quantity_based,
                self.get_company_for_user.currency,
            ),
            "closed_change_text": self.format_change_text(
                current_data["closed"],
                previous_data["closed"],
                previous_period.name,
                forecast_type.is_quantity_based,
                self.get_company_for_user.currency,
            ),
        }

    def get_bulk_trend_data(self, periods, forecast_type, user_id=None):
        """
        Properly handle both single user and multi-user individual trends
        """
        if len(periods) < 2:
            return {}

        query_params = {
            "forecast_type": forecast_type,
            "fiscal_year": periods[0].quarter.fiscal_year,
            "period__in": periods,
        }
        if user_id:
            query_params["owner_id"] = user_id

        all_forecasts = Forecast.objects.filter(**query_params).values(
            "period_id",
            "period__period_number",
            "owner_id",
            "commit_quantity" if forecast_type.is_quantity_based else "commit_amount",
            (
                "best_case_quantity"
                if forecast_type.is_quantity_based
                else "best_case_amount"
            ),
            (
                "pipeline_quantity"
                if forecast_type.is_quantity_based
                else "pipeline_amount"
            ),
            "closed_quantity" if forecast_type.is_quantity_based else "closed_amount",
        )

        field_suffix = "quantity" if forecast_type.is_quantity_based else "amount"

        period_data = {}
        user_period_data = {}

        for forecast in all_forecasts:
            period_id = forecast["period_id"]
            owner_id = forecast["owner_id"]

            if period_id not in period_data:
                period_data[period_id] = {
                    "period_number": forecast["period__period_number"],
                    "commit": 0,
                    "best_case": 0,
                    "pipeline": 0,
                    "closed": 0,
                }

            period_data[period_id]["commit"] += (
                forecast.get(f"commit_{field_suffix}", 0) or 0
            )
            period_data[period_id]["best_case"] += (
                forecast.get(f"best_case_{field_suffix}", 0) or 0
            )
            period_data[period_id]["pipeline"] += (
                forecast.get(f"pipeline_{field_suffix}", 0) or 0
            )
            period_data[period_id]["closed"] += (
                forecast.get(f"closed_{field_suffix}", 0) or 0
            )

            if owner_id not in user_period_data:
                user_period_data[owner_id] = {}

            if period_id not in user_period_data[owner_id]:
                user_period_data[owner_id][period_id] = {
                    "period_number": forecast["period__period_number"],
                    "commit": 0,
                    "best_case": 0,
                    "pipeline": 0,
                    "closed": 0,
                }

            user_period_data[owner_id][period_id]["commit"] = (
                forecast.get(f"commit_{field_suffix}", 0) or 0
            )
            user_period_data[owner_id][period_id]["best_case"] = (
                forecast.get(f"best_case_{field_suffix}", 0) or 0
            )
            user_period_data[owner_id][period_id]["pipeline"] = (
                forecast.get(f"pipeline_{field_suffix}", 0) or 0
            )
            user_period_data[owner_id][period_id]["closed"] = (
                forecast.get(f"closed_{field_suffix}", 0) or 0
            )

        # Calculate trends
        trend_results = {}
        sorted_periods = sorted(periods, key=lambda p: p.period_number)

        for i, period in enumerate(sorted_periods):
            if i == 0:  # First period has no previous data
                continue

            current_data = period_data.get(
                period.id, {"commit": 0, "best_case": 0, "pipeline": 0, "closed": 0}
            )
            previous_period = sorted_periods[i - 1]
            previous_data = period_data.get(
                previous_period.id,
                {"commit": 0, "best_case": 0, "pipeline": 0, "closed": 0},
            )

            # Period-level trends (for main aggregated row)
            trend_results[period.id] = {
                "commit_trend": self.calculate_trend_direction(
                    current_data["commit"], previous_data["commit"]
                ),
                "best_case_trend": self.calculate_trend_direction(
                    current_data["best_case"], previous_data["best_case"]
                ),
                "pipeline_trend": self.calculate_trend_direction(
                    current_data["pipeline"], previous_data["pipeline"]
                ),
                "closed_trend": self.calculate_trend_direction(
                    current_data["closed"], previous_data["closed"]
                ),
                "commit_change_text": self.format_change_text(
                    current_data["commit"],
                    previous_data["commit"],
                    previous_period.name,
                    forecast_type.is_quantity_based,
                    self.get_company_for_user.currency,
                ),
                "best_case_change_text": self.format_change_text(
                    current_data["best_case"],
                    previous_data["best_case"],
                    previous_period.name,
                    forecast_type.is_quantity_based,
                    self.get_company_for_user.currency,
                ),
                "pipeline_change_text": self.format_change_text(
                    current_data["pipeline"],
                    previous_data["pipeline"],
                    previous_period.name,
                    forecast_type.is_quantity_based,
                    self.get_company_for_user.currency,
                ),
                "closed_change_text": self.format_change_text(
                    current_data["closed"],
                    previous_data["closed"],
                    previous_period.name,
                    forecast_type.is_quantity_based,
                    self.get_company_for_user.currency,
                ),
                "user_data": user_period_data,
                "previous_period_id": previous_period.id,
            }

        return trend_results

    def enhance_forecast_data_bulk(
        self,
        forecast,
        currency_symbol,
        period=None,
        forecast_type=None,
        trend_data=None,
    ):
        """
        FIXED: Enhanced forecast data with proper individual user trend handling
        """
        gap_to_target = (
            (forecast.target_quantity - forecast.actual_quantity)
            if forecast.forecast_type.is_quantity_based
            and hasattr(forecast, "target_quantity")
            and forecast.target_quantity
            and forecast.actual_quantity
            else (
                (forecast.target_amount - forecast.actual_amount)
                if hasattr(forecast, "target_amount")
                and forecast.target_amount
                and forecast.actual_amount
                else 0
            )
        )

        is_on_track = (
            forecast.actual_quantity >= forecast.commit_quantity
            if forecast.forecast_type.is_quantity_based
            and forecast.actual_quantity
            and forecast.commit_quantity
            else (
                forecast.actual_amount >= forecast.commit_amount
                if forecast.actual_amount and forecast.commit_amount
                else False
            )
        )

        forecast.gap_to_target = gap_to_target
        forecast.is_on_track = is_on_track
        forecast.currency_symbol = currency_symbol

        if (
            trend_data
            and period
            and period.id in trend_data
            and hasattr(forecast, "owner")
            and forecast.owner
        ):
            period_trend_data = trend_data[period.id]

            if (
                "user_data" in period_trend_data
                and "previous_period_id" in period_trend_data
            ):
                user_data = period_trend_data["user_data"].get(forecast.owner.id, {})
                previous_period_id = period_trend_data["previous_period_id"]

                current_user_data = user_data.get(
                    period.id, {"commit": 0, "best_case": 0, "pipeline": 0, "closed": 0}
                )
                previous_user_data = user_data.get(
                    previous_period_id,
                    {"commit": 0, "best_case": 0, "pipeline": 0, "closed": 0},
                )

                forecast.commit_trend = self.calculate_trend_direction(
                    current_user_data["commit"], previous_user_data["commit"]
                )
                forecast.best_case_trend = self.calculate_trend_direction(
                    current_user_data["best_case"], previous_user_data["best_case"]
                )
                forecast.pipeline_trend = self.calculate_trend_direction(
                    current_user_data["pipeline"], previous_user_data["pipeline"]
                )
                forecast.closed_trend = self.calculate_trend_direction(
                    current_user_data["closed"], previous_user_data["closed"]
                )

                try:
                    previous_period = Period.objects.get(id=previous_period_id)
                    forecast.commit_change_text = self.format_change_text(
                        current_user_data["commit"],
                        previous_user_data["commit"],
                        previous_period.name,
                        forecast_type.is_quantity_based,
                        self.get_company_for_user.currency,
                    )
                    forecast.best_case_change_text = self.format_change_text(
                        current_user_data["best_case"],
                        previous_user_data["best_case"],
                        previous_period.name,
                        forecast_type.is_quantity_based,
                        self.get_company_for_user.currency,
                    )
                    forecast.pipeline_change_text = self.format_change_text(
                        current_user_data["pipeline"],
                        previous_user_data["pipeline"],
                        previous_period.name,
                        forecast_type.is_quantity_based,
                        self.get_company_for_user.currency,
                    )
                    forecast.closed_change_text = self.format_change_text(
                        current_user_data["closed"],
                        previous_user_data["closed"],
                        previous_period.name,
                        forecast_type.is_quantity_based,
                        self.get_company_for_user.currency,
                    )
                except Period.DoesNotExist:
                    forecast.commit_change_text = ""
                    forecast.best_case_change_text = ""
                    forecast.pipeline_change_text = ""
                    forecast.closed_change_text = ""
            else:
                # Use period-level trends as fallback
                forecast.commit_trend = period_trend_data.get("commit_trend")
                forecast.best_case_trend = period_trend_data.get("best_case_trend")
                forecast.pipeline_trend = period_trend_data.get("pipeline_trend")
                forecast.closed_trend = period_trend_data.get("closed_trend")
                forecast.commit_change_text = period_trend_data.get(
                    "commit_change_text", ""
                )
                forecast.best_case_change_text = period_trend_data.get(
                    "best_case_change_text", ""
                )
                forecast.pipeline_change_text = period_trend_data.get(
                    "pipeline_change_text", ""
                )
                forecast.closed_change_text = period_trend_data.get(
                    "closed_change_text", ""
                )
        else:
            # No trend data available
            forecast.commit_trend = None
            forecast.best_case_trend = None
            forecast.pipeline_trend = None
            forecast.closed_trend = None
            forecast.commit_change_text = ""
            forecast.best_case_change_text = ""
            forecast.pipeline_change_text = ""
            forecast.closed_change_text = ""

        return forecast

    def create_empty_user_forecast(
        self, period, forecast_type, user_id, currency_symbol, target=None
    ):
        """Create a placeholder forecast for a user with no data."""

        class EmptyUserForecast:
            """Placeholder forecast with zero values for users without data."""

            def __init__(self):
                self.id = f"empty_{period.id}_{user_id}"
                self.period = period
                self.quarter = period.quarter
                self.fiscal_year = period.quarter.fiscal_year
                self.forecast_type = forecast_type
                self.currency_symbol = currency_symbol
                self.owner = User.objects.get(id=user_id)

                if target and forecast_type.is_quantity_based:
                    self.target_quantity = target.target_amount
                    self.pipeline_quantity = 0
                    self.best_case_quantity = 0
                    self.commit_quantity = 0
                    self.closed_quantity = 0
                    self.actual_quantity = 0
                    self.gap_quantity = self.target_quantity
                elif target:
                    self.target_amount = target.target_amount
                    self.pipeline_amount = 0
                    self.best_case_amount = 0
                    self.commit_amount = 0
                    self.closed_amount = 0
                    self.actual_amount = 0
                    self.gap_amount = self.target_amount
                else:
                    if forecast_type.is_quantity_based:
                        self.target_quantity = 0
                        self.pipeline_quantity = 0
                        self.best_case_quantity = 0
                        self.commit_quantity = 0
                        self.closed_quantity = 0
                        self.actual_quantity = 0
                        self.gap_quantity = 0
                    else:
                        self.target_amount = 0
                        self.pipeline_amount = 0
                        self.best_case_amount = 0
                        self.commit_amount = 0
                        self.closed_amount = 0
                        self.actual_amount = 0
                        self.gap_amount = 0

                self.performance_percentage = 0
                self.gap_percentage = 0
                self.closed_percentage = 0
                self.closed_deals_count = 0

        empty_forecast = EmptyUserForecast()
        aggregated_forecast = self.create_aggregated_forecast(
            period, forecast_type, [empty_forecast], currency_symbol, user_id, target
        )
        aggregated_forecast.user_forecasts = []
        return aggregated_forecast

    def create_aggregated_forecast(
        self,
        period,
        forecast_type,
        user_forecasts,
        currency_symbol,
        _user_id=None,
        target=None,
    ):
        """Create aggregated forecast with optimized calculations and target integration."""

        class AggregatedForecast:
            """
            Aggregated forecast data for a SINGLE period, combining data
            from multiple users for that specific period.
            """

            def __init__(self):
                self.id = f"period_{period.id}"
                self.period = period
                self.quarter = period.quarter
                self.fiscal_year = period.quarter.fiscal_year
                self.forecast_type = forecast_type
                self.currency_symbol = currency_symbol
                self.commit_trend = None
                self.best_case_trend = None
                self.pipeline_trend = None
                self.closed_trend = None
                self.commit_change_text = ""
                self.best_case_change_text = ""
                self.pipeline_change_text = ""
                self.closed_change_text = ""

                # Initialize pagination attributes for multi-user view
                self.has_next = False
                self.next_page = None
                self.view_id = None
                self.user_forecasts = []

                if target and forecast_type.is_quantity_based:
                    self.target_quantity = (
                        target.target_amount if hasattr(target, "target_amount") else 0
                    )
                    self.pipeline_quantity = 0
                    self.best_case_quantity = 0
                    self.commit_quantity = 0
                    self.closed_quantity = 0
                    self.actual_quantity = 0
                    self.gap_quantity = 0
                elif target:
                    self.target_amount = (
                        target.target_amount if hasattr(target, "target_amount") else 0
                    )
                    self.pipeline_amount = 0
                    self.best_case_amount = 0
                    self.commit_amount = 0
                    self.closed_amount = 0
                    self.actual_amount = 0
                    self.gap_amount = 0
                else:
                    if forecast_type.is_quantity_based:
                        self.target_quantity = 0
                        self.pipeline_quantity = 0
                        self.best_case_quantity = 0
                        self.commit_quantity = 0
                        self.closed_quantity = 0
                        self.actual_quantity = 0
                        self.gap_quantity = 0
                    else:
                        self.target_amount = 0
                        self.pipeline_amount = 0
                        self.best_case_amount = 0
                        self.commit_amount = 0
                        self.closed_amount = 0
                        self.actual_amount = 0
                        self.gap_amount = 0

                self.performance_percentage = 0
                self.gap_percentage = 0
                self.closed_percentage = 0
                self.closed_deals_count = 0

        aggregated = AggregatedForecast()

        if user_forecasts:
            if forecast_type.is_quantity_based:
                aggregated.pipeline_quantity = sum(
                    f.pipeline_quantity or 0 for f in user_forecasts
                )
                aggregated.best_case_quantity = sum(
                    f.best_case_quantity or 0 for f in user_forecasts
                )
                aggregated.commit_quantity = sum(
                    f.commit_quantity or 0 for f in user_forecasts
                )
                aggregated.closed_quantity = sum(
                    f.closed_quantity or 0 for f in user_forecasts
                )
                aggregated.actual_quantity = sum(
                    f.actual_quantity or 0 for f in user_forecasts
                )

                if aggregated.target_quantity > 0:
                    aggregated.gap_quantity = (
                        aggregated.target_quantity - aggregated.actual_quantity
                    )
                    aggregated.performance_percentage = (
                        aggregated.actual_quantity / aggregated.target_quantity
                    ) * 100
                    aggregated.gap_percentage = (
                        aggregated.gap_quantity / aggregated.target_quantity
                    ) * 100
                    aggregated.closed_percentage = (
                        aggregated.closed_quantity / aggregated.target_quantity
                    ) * 100
            else:
                aggregated.pipeline_amount = sum(
                    f.pipeline_amount or 0 for f in user_forecasts
                )
                aggregated.best_case_amount = sum(
                    f.best_case_amount or 0 for f in user_forecasts
                )
                aggregated.commit_amount = sum(
                    f.commit_amount or 0 for f in user_forecasts
                )
                aggregated.closed_amount = sum(
                    f.closed_amount or 0 for f in user_forecasts
                )
                aggregated.actual_amount = sum(
                    f.actual_amount or 0 for f in user_forecasts
                )

                if aggregated.target_amount > 0:
                    aggregated.gap_amount = (
                        aggregated.target_amount - aggregated.actual_amount
                    )
                    aggregated.performance_percentage = (
                        aggregated.actual_amount / aggregated.target_amount
                    ) * 100
                    aggregated.gap_percentage = (
                        aggregated.gap_amount / aggregated.target_amount
                    ) * 100
                    aggregated.closed_percentage = (
                        aggregated.closed_amount / aggregated.target_amount
                    ) * 100

            aggregated.closed_deals_count = len(user_forecasts)

        return aggregated
