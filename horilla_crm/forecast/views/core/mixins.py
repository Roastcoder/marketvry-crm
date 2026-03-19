"""Data-fetching mixin for ForecastTypeTabView (fiscal year, targets, get_forecast_data)."""

# Third-party imports (Django)
from django.core.paginator import Paginator
from django.utils.functional import cached_property

# First-party / Horilla imports
from horilla.auth.models import User
from horilla.utils.translation import gettext_lazy as _
from horilla_core.models import Company, FiscalYearInstance, Period
from horilla_crm.forecast.models import Forecast, ForecastTarget
from horilla_crm.forecast.utils import ForecastCalculator


class ForecastTypeTabMixin:
    """Mixin with get_forecast_data and fiscal/target/ensure methods."""

    @cached_property
    def get_current_fiscal_year(self):
        """Cache the current fiscal year to avoid repeated queries."""
        return FiscalYearInstance.objects.filter(is_current=True).first()

    @cached_property
    def get_company_for_user(self):
        """Cache the active company for the current user."""
        return (
            self.request.active_company
            if hasattr(self.request, "active_company")
            else Company.objects.filter(id=self.request.user.company_id).first()
        )

    def get_target_for_period_bulk(self, periods, forecast_type, user_id=None):
        """
        Get targets for all periods in bulk to avoid N+1 queries
        """
        if user_id:
            # Get individual targets for specific user
            targets = ForecastTarget.objects.filter(
                is_active=True,
                assigned_to_id=user_id,
                period__in=periods,
                forcasts_type=forecast_type,  # Corrected from forcasts_type
            ).select_related("period", "assigned_to")

            target_map = {target.period_id: target for target in targets}

            # For missing individual targets, check role-based targets
            missing_periods = [p for p in periods if p.id not in target_map]
            if missing_periods:
                try:
                    user = User.objects.get(id=user_id)
                    if hasattr(user, "role") and user.role:
                        role_targets = ForecastTarget.objects.filter(
                            is_active=True,
                            period__in=missing_periods,
                            forcasts_type=forecast_type,  # Corrected from forcasts_type
                            role=user.role,
                            assigned_to__isnull=True,
                        ).select_related("period")

                        for role_target in role_targets:
                            if role_target.period_id not in target_map:
                                target_map[role_target.period_id] = role_target
                except User.DoesNotExist:
                    pass

            return target_map
        all_targets = (
            ForecastTarget.objects.filter(
                is_active=True,
                period__in=periods,
                forcasts_type=forecast_type,  # Corrected from forcasts_type
            )
            .select_related("period", "assigned_to")
            .prefetch_related("role")
        )

        targets_by_period = {}
        for target in all_targets:
            period_id = target.period_id
            if period_id not in targets_by_period:
                targets_by_period[period_id] = []
            targets_by_period[period_id].append(target)

        return targets_by_period

    def ensure_forecasts_exist(self, forecast_type, fiscal_year):
        """
        Bulk create missing forecasts to reduce database operations
        """
        calculator = ForecastCalculator(user=self.request.user, fiscal_year=fiscal_year)

        all_users = list(User.objects.filter(is_active=True).values("id"))
        all_periods = list(
            Period.objects.filter(quarter__fiscal_year=fiscal_year).values("id")
        )

        existing_forecasts = set(
            Forecast.objects.filter(
                forecast_type=forecast_type, fiscal_year=fiscal_year
            ).values_list("owner_id", "period_id")
        )

        missing_forecasts = []
        for user in all_users:
            for period in all_periods:
                combination = (user["id"], period["id"])
                if combination not in existing_forecasts:
                    missing_forecasts.append((user["id"], period["id"]))

        # Bulk create missing forecasts
        if missing_forecasts:
            calculator.bulk_create_missing_forecasts(forecast_type, missing_forecasts)

    def get_forecast_data(self, forecast_type, fiscal_year, user_id=None, page=1):
        """
        COMPLETE FIX for single user trend data display
        """
        periods = (
            Period.objects.filter(quarter__fiscal_year=fiscal_year)
            .select_related("quarter")
            .order_by("period_number")
        )

        currency_symbol = (
            self.get_company_for_user.currency if self.get_company_for_user else "USD"
        )

        periods_list = list(periods)
        targets_data = self.get_target_for_period_bulk(
            periods_list, forecast_type, user_id
        )

        forecast_queryset = Forecast.objects.filter(
            forecast_type=forecast_type, fiscal_year=fiscal_year
        ).select_related("owner", "forecast_type", "period", "quarter")

        if user_id:
            forecast_queryset = forecast_queryset.filter(owner_id=user_id)
        else:
            forecast_queryset = forecast_queryset.filter(
                owner__is_active=True
            ).prefetch_related("owner")

        forecasts_by_period = {}
        for forecast in forecast_queryset:
            period_id = forecast.period_id
            if period_id not in forecasts_by_period:
                forecasts_by_period[period_id] = []
            forecasts_by_period[period_id].append(forecast)

        # Get trend data - this is crucial for single users
        trend_data = (
            self.get_bulk_trend_data(periods_list, forecast_type, user_id)
            if periods_list
            else {}
        )

        period_forecasts = []
        for period in periods_list:
            user_forecasts = forecasts_by_period.get(period.id, [])
            target = self.extract_target_from_bulk(
                targets_data, period, None if not user_id else user_id
            )

            if user_id:
                # SINGLE USER VIEW - This is where the fix is critical
                if not user_forecasts:
                    # Create empty forecast for user with no data
                    try:
                        user = User.objects.get(id=user_id)
                        empty_forecast = Forecast()
                        empty_forecast.id = f"empty_{period.id}_{user_id}"
                        empty_forecast.period = period
                        empty_forecast.quarter = period.quarter
                        empty_forecast.fiscal_year = period.quarter.fiscal_year
                        empty_forecast.forecast_type = forecast_type
                        empty_forecast.owner = user
                        empty_forecast.owner_id = user.id

                        # Initialize all fields to 0
                        if forecast_type.is_quantity_based:
                            empty_forecast.target_quantity = (
                                target.target_amount if target else 0
                            )
                            empty_forecast.pipeline_quantity = 0
                            empty_forecast.best_case_quantity = 0
                            empty_forecast.commit_quantity = 0
                            empty_forecast.closed_quantity = 0
                            empty_forecast.actual_quantity = 0
                        else:
                            empty_forecast.target_amount = (
                                target.target_amount if target else 0
                            )
                            empty_forecast.pipeline_amount = 0
                            empty_forecast.best_case_amount = 0
                            empty_forecast.commit_amount = 0
                            empty_forecast.closed_amount = 0
                            empty_forecast.actual_amount = 0

                        user_forecasts = [empty_forecast]
                    except User.DoesNotExist:
                        user_forecasts = []

                # Create aggregated forecast
                aggregated_forecast = self.create_aggregated_forecast(
                    period,
                    forecast_type,
                    user_forecasts,
                    currency_symbol,
                    user_id,
                    target,
                )

                if trend_data and period.id in trend_data:
                    period_trend = trend_data[period.id]

                    aggregated_forecast.commit_trend = period_trend.get("commit_trend")
                    aggregated_forecast.best_case_trend = period_trend.get(
                        "best_case_trend"
                    )
                    aggregated_forecast.pipeline_trend = period_trend.get(
                        "pipeline_trend"
                    )
                    aggregated_forecast.closed_trend = period_trend.get("closed_trend")
                    aggregated_forecast.commit_change_text = period_trend.get(
                        "commit_change_text", ""
                    )
                    aggregated_forecast.best_case_change_text = period_trend.get(
                        "best_case_change_text", ""
                    )
                    aggregated_forecast.pipeline_change_text = period_trend.get(
                        "pipeline_change_text", ""
                    )
                    aggregated_forecast.closed_change_text = period_trend.get(
                        "closed_change_text", ""
                    )

                else:
                    aggregated_forecast.commit_trend = None
                    aggregated_forecast.best_case_trend = None
                    aggregated_forecast.pipeline_trend = None
                    aggregated_forecast.closed_trend = None
                    aggregated_forecast.commit_change_text = ""
                    aggregated_forecast.best_case_change_text = ""
                    aggregated_forecast.pipeline_change_text = ""
                    aggregated_forecast.closed_change_text = ""

                aggregated_forecast.user_forecasts = []

            else:
                users_with_data = []
                users_without_data = []
                all_active_users = User.objects.select_related("role").filter(
                    is_active=True
                )
                user_targets = self.get_target_for_period_bulk(
                    [period], forecast_type, None
                )
                user_target_map = {
                    target.assigned_to_id: target
                    for target in user_targets.get(period.id, [])
                }

                for user in all_active_users:
                    user_forecast = next(
                        (f for f in user_forecasts if f.owner_id == user.id), None
                    )
                    user_specific_target = user_target_map.get(user.id)

                    if user_forecast:
                        if user_specific_target:
                            if forecast_type.is_quantity_based:
                                user_forecast.target_quantity = (
                                    user_specific_target.target_amount
                                )
                            else:
                                user_forecast.target_amount = (
                                    user_specific_target.target_amount
                                )
                        else:
                            if forecast_type.is_quantity_based:
                                user_forecast.target_quantity = 0
                            else:
                                user_forecast.target_amount = 0

                        has_data = (
                            forecast_type.is_quantity_based
                            and (
                                user_forecast.actual_quantity > 0
                                or user_forecast.pipeline_quantity > 0
                                or user_forecast.best_case_quantity > 0
                                or user_forecast.commit_quantity > 0
                                or user_forecast.closed_quantity > 0
                            )
                        ) or (
                            not forecast_type.is_quantity_based
                            and (
                                user_forecast.actual_amount > 0
                                or user_forecast.pipeline_amount > 0
                                or user_forecast.best_case_amount > 0
                                or user_forecast.commit_amount > 0
                                or user_forecast.closed_amount > 0
                            )
                        )
                        if has_data:
                            users_with_data.append(user_forecast)
                        else:
                            users_without_data.append(user_forecast)
                    else:
                        # Create empty forecast for users without data
                        empty_forecast = Forecast()
                        empty_forecast.id = f"empty_{period.id}_{user.id}"
                        empty_forecast.period = period
                        empty_forecast.quarter = period.quarter
                        empty_forecast.fiscal_year = period.quarter.fiscal_year
                        empty_forecast.forecast_type = forecast_type
                        empty_forecast.owner = user
                        empty_forecast.owner_id = user.id

                        if forecast_type.is_quantity_based:
                            empty_forecast.target_quantity = (
                                user_specific_target.target_amount
                                if user_specific_target
                                else 0
                            )
                            empty_forecast.pipeline_quantity = 0
                            empty_forecast.best_case_quantity = 0
                            empty_forecast.commit_quantity = 0
                            empty_forecast.closed_quantity = 0
                            empty_forecast.actual_quantity = 0
                        else:
                            empty_forecast.target_amount = (
                                user_specific_target.target_amount
                                if user_specific_target
                                else 0
                            )
                            empty_forecast.pipeline_amount = 0
                            empty_forecast.best_case_amount = 0
                            empty_forecast.commit_amount = 0
                            empty_forecast.closed_amount = 0
                            empty_forecast.actual_amount = 0

                        users_without_data.append(empty_forecast)

                # Sort users with data
                if forecast_type.is_quantity_based:
                    users_with_data.sort(
                        key=lambda f: getattr(f, "actual_quantity", 0) or 0,
                        reverse=True,
                    )
                else:
                    users_with_data.sort(
                        key=lambda f: getattr(f, "actual_amount", 0) or 0, reverse=True
                    )

                sorted_user_forecasts = users_with_data + users_without_data

                paginator = Paginator(sorted_user_forecasts, self.USERS_PER_PAGE)
                try:
                    paginated_user_forecasts = paginator.page(page)
                except Exception:
                    paginated_user_forecasts = paginator.page(1)

                aggregated_forecast = self.create_aggregated_forecast(
                    period,
                    forecast_type,
                    user_forecasts,
                    currency_symbol,
                    user_id,
                    target,
                )

                # Apply trend data to aggregated forecast
                if period.id in trend_data:
                    period_trend = trend_data[period.id]
                    aggregated_forecast.commit_trend = period_trend.get("commit_trend")
                    aggregated_forecast.best_case_trend = period_trend.get(
                        "best_case_trend"
                    )
                    aggregated_forecast.pipeline_trend = period_trend.get(
                        "pipeline_trend"
                    )
                    aggregated_forecast.closed_trend = period_trend.get("closed_trend")
                    aggregated_forecast.commit_change_text = period_trend.get(
                        "commit_change_text", ""
                    )
                    aggregated_forecast.best_case_change_text = period_trend.get(
                        "best_case_change_text", ""
                    )
                    aggregated_forecast.pipeline_change_text = period_trend.get(
                        "pipeline_change_text", ""
                    )
                    aggregated_forecast.closed_change_text = period_trend.get(
                        "closed_change_text", ""
                    )

                # Attach paginated user forecasts with individual trend data
                aggregated_forecast.user_forecasts = [
                    self.enhance_forecast_data_bulk(
                        f, currency_symbol, period, forecast_type, trend_data
                    )
                    for f in paginated_user_forecasts
                ]
                aggregated_forecast.has_next = paginated_user_forecasts.has_next()
                aggregated_forecast.next_page = (
                    paginated_user_forecasts.next_page_number()
                    if paginated_user_forecasts.has_next()
                    else None
                )
                aggregated_forecast.view_id = f"period_{period.id}"

            period_forecasts.append(aggregated_forecast)

        return period_forecasts
