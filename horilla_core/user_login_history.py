"""
This view handles the methods for user login history view
"""

# Third-party imports (Django)
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _

# First-party / Horilla imports
from horilla_core.decorators import htmx_required
from horilla_generics.views import HorillaListView, HorillaNavView, HorillaView


class UserLoginHistoryView(LoginRequiredMixin, HorillaView):
    """
    Main login history view of user
    """

    template_name = "settings/users/users_login_history_view.html"
    nav_url = reverse_lazy("horilla_core:user_login_history_nav")
    list_url = reverse_lazy("horilla_core:user_login_history_list")


@method_decorator(htmx_required, name="dispatch")
class UserLoginHistoryNavbar(LoginRequiredMixin, HorillaNavView):
    """
    user Login history navbar
    """

    from login_history.models import LoginHistory

    nav_title = _("My Login History")
    search_url = reverse_lazy("horilla_core:user_login_history_list")
    main_url = reverse_lazy("horilla_core:user_login_history_view")
    model_name = "LoginHistory"
    model_app_label = "loginhistory"
    nav_width = False
    gap_enabled = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    search_option = False


@method_decorator(htmx_required, name="dispatch")
class UserloginHistoryListView(LoginRequiredMixin, HorillaListView):
    """
    Login History list view of the user
    """

    from login_history.models import LoginHistory

    model = LoginHistory
    view_id = "UserLoginHistory"

    search_url = reverse_lazy("horilla_core:user_login_history_list")
    main_url = reverse_lazy("horilla_core:login_history_view")
    bulk_delete_enabled = False
    bulk_update_option = False
    enable_sorting = False
    table_width = False
    table_height = False
    table_height_as_class = "h-[500px]"

    def get_queryset(self):
        user = self.request.user
        app_label = self.model._meta.app_label
        model_name = self.model._meta.model_name

        queryset = self.model.objects.all()

        # if user.has_perm(f"{app_label}.view_{model_name}"):
        #     pass
        # elif user.has_perm(f"{app_label}.view_own_{model_name}"):
        #     queryset = queryset.filter(user_id=user)
        # else:
        #     queryset = queryset.none()

        return queryset

    columns = [
        (_("Browser"), "short_user_agent"),
        (_("Login Time"), "formatted_datetime"),
        (_("Is Active"), "is_login_icon"),
        (_("IP"), "ip"),
        (_("Status"), "user_status"),
    ]
