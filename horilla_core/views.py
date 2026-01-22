"""
A generic class-based view for rendering the home page.
"""

# Standard library imports
import json
import logging
import os
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse

# Third-party imports (other)
import pycountry

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property  # type: ignore
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import TemplateView
from django.views.generic.base import RedirectView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken

# First-party / Horilla imports
from horilla import settings
from horilla.auth.models import User
from horilla.exceptions import HorillaHttp404
from horilla.utils.branding import load_branding
from horilla_core.decorators import htmx_required, permission_required_or_denied
from horilla_core.forms import (
    BusinessHourForm,
    CompanyFormClassSingle,
    CompanyMultistepFormClass,
    HolidayForm,
)
from horilla_core.initialiaze_database import InitializeDatabaseConditionView
from horilla_core.models import (
    ActiveTab,
    BusinessHour,
    Company,
    DatedConversionRate,
    Holiday,
    MultipleCurrency,
    Role,
)
from horilla_generics.views import (
    HorillaListView,
    HorillaModalDetailView,
    HorillaMultiStepFormView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaTabView,
)
from horilla_mail.models import HorillaMailConfiguration

from .signals import company_created, pre_login_render_signal, pre_logout_signal

logger = logging.getLogger(__name__)


def is_jwt_token_valid(auth_header):
    """Check if the provided JWT token is valid and return the associated user."""
    if not auth_header or not auth_header.startswith("Bearer "):
        return None  # No token

    token = auth_header.split("Bearer ")[1].strip()
    try:
        UntypedToken(token)  # Will raise if invalid
        validated_token = JWTAuthentication().get_validated_token(token)
        user = JWTAuthentication().get_user(validated_token)
        return user
    except (InvalidToken, TokenError):
        return None


def protected_media(request, path):
    """Serve protected media files with access control."""
    public_pages = [
        "/login",
        "/sign-up-user",
        "/forgot-password",
        "/change-password",
        "/reset-password",
        "/initialize-database",
        "/initialize-database-user",
        "/initialize-database-role",
        "/initialize-database-company",
        "/initialize-company-form",
        "/load-data" "/load-demo-data",
    ]
    exempted_folders = ["assets/icons/"]

    media_path = os.path.join(settings.MEDIA_ROOT, path)
    if not os.path.exists(media_path):
        raise HorillaHttp404("File not found")

    referer_path = urlparse(request.META.get("HTTP_REFERER", "")).path

    # Try Bearer token auth
    jwt_user = is_jwt_token_valid(request.META.get("HTTP_AUTHORIZATION", ""))

    # Access control logic
    if referer_path not in public_pages and not any(
        path.startswith(f) for f in exempted_folders
    ):
        if not request.user.is_authenticated and not jwt_user:
            messages.error(
                request,
                "You must be logged in or provide a valid token to access this file.",
            )
            next_url = f"/media/{path}"
            login_url = (
                f"{redirect('horilla_core:login').url}?{urlencode({'next': next_url})}"
            )
            return redirect(login_url)

    return FileResponse(open(media_path, "rb"))


class HomePageView(LoginRequiredMixin, View):
    """
    Redirect to default home page
    """

    def get(self, request, *args, **kwargs):
        """
        Redirect to default home page
        """

        return redirect(settings.DEFAULT_HOME_REDIRECT)


@method_decorator(htmx_required, name="dispatch")
class ReloadMessages(LoginRequiredMixin, TemplateView):
    """
    Reload messages
    """

    template_name = "messages.html"

    def get_context_data(self, **kwargs):
        """
        Get context data for reloading messages.
        """

        context = super().get_context_data(**kwargs)
        return context


class SaveActiveTabView(LoginRequiredMixin, View):
    """
    View to save the active tab for a user.
    """

    def post(self, request, *args, **kwargs):
        """
        Save the active tab for the user.
        """
        tab_target = request.POST.get("tab_target")
        path = request.POST.get("path")
        user = request.user if request.user.is_authenticated else None
        company = getattr(request, "active_company", None)

        if user and tab_target and path:
            ActiveTab.objects.update_or_create(
                created_by=user,
                path=path,
                company=company if company else user.company,
                defaults={"tab_target": tab_target},
            )
            return JsonResponse({"status": "success"})

        return JsonResponse({"status": "error", "message": "Invalid data"}, status=400)

    def get(self, request, *args, **kwargs):
        """
        Handle GET requests with an error response.
        """

        return JsonResponse(
            {"status": "error", "message": "Invalid method"}, status=405
        )


class LoginUserView(View):
    """
    Class-based view to handle user login.
    """

    def get(self, request):
        """
        Render login page with an optional 'next' param preserved.
        """
        next_url = request.GET.get("next", "/")
        condition_view = InitializeDatabaseConditionView()
        initialize_database = condition_view.get_initialize_condition()
        show_forgot_password = False
        hq_company = Company.objects.filter(hq=True).first()

        if hq_company:
            show_forgot_password = HorillaMailConfiguration.objects.filter(
                company=hq_company
            ).exists()

        context = {
            "next": next_url,
            "initialize_database": initialize_database,
            "show_forgot_password": show_forgot_password,
        }

        _responses = pre_login_render_signal.send(
            sender=self.__class__, request=request, context=context
        )

        return render(request, "login.html", context=context)

    def post(self, request):
        """
        Handle login attempt with **two valid methods**:
        1. Email + Phone number
        2. Username + Password
        """
        identifier = request.POST.get("username")
        secret = request.POST.get("password")
        next_url = request.POST.get("next", "/")

        user = None

        user_by_email_phone = User.objects.filter(
            email=identifier, contact_number=secret
        ).first()
        if user_by_email_phone:
            user = user_by_email_phone

        if not user:
            user = authenticate(request, username=identifier, password=secret)

        if not user:
            messages.error(
                request, _("Invalid credentials. Please check and try again.")
            )
            return redirect(reverse_lazy("horilla_core:login") + f"?next={next_url}")

        if not user.is_active:
            messages.warning(
                request,
                _("This user is archived or blocked. Please contact support."),
            )
            # return render(request, "login.html", {"next": next_url})
            return redirect(reverse_lazy("horilla_core:login") + f"?next={next_url}")

        login(request, user)
        messages.success(request, _("Login successful."))

        if not url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}
        ):
            next_url = "/"

        return redirect(next_url)


class LogoutView(View):
    """
    Class-based view to logout the user and clear local storage.
    All preservation logic is handled by signal receivers.
    """

    def get(self, request, *args, **kwargs):
        """
        Logout the user and clear local storage.
        """

        # Collect data from all registered signal receivers
        storage_data = {}

        if request.user.is_authenticated:
            responses = pre_logout_signal.send(sender=self.__class__, request=request)

            for _receiver, response in responses:
                if response and isinstance(response, tuple) and len(response) == 2:
                    storage_key, data = response
                    if storage_key and data:
                        storage_data[storage_key] = data

        if request.user.is_authenticated:
            logout(request)

        storage_data_json = json.dumps(storage_data) if storage_data else "{}"

        script_content = f"""
        <script>
            // Save theme mode before clearing (always preserved)
            const theme = localStorage.getItem('theme');

            // Clear everything
            localStorage.clear();

            // Always restore theme mode if it existed
            if (theme !== null) {{
                localStorage.setItem('theme', theme);
            }}

            const storageData = {storage_data_json};
            for (const [key, value] of Object.entries(storageData)) {{
                localStorage.setItem(key, JSON.stringify(value));
            }}
        </script>

        <meta http-equiv="refresh" content="0;url=/login">
        """

        response = HttpResponse()
        response.content = script_content
        return response


class ConmpanyInformationTabView(LoginRequiredMixin, HorillaTabView):
    """
    A generic class-based view for rendering the company information settings page.
    """

    view_id = "company-information-view"
    background_class = "bg-primary-100 rounded-md"

    @cached_property
    def tabs(self):
        """
        Get the list of tabs for the company information view.
        """
        tabs = []

        # Company Details Tab
        if self.request.user.has_perm("horilla_core.view_company"):
            tabs.append(
                {
                    "title": _("Details"),
                    "url": reverse_lazy("horilla_core:company_details_tab"),
                    "target": "company-information-view-content",
                    "id": "company-information-view",
                }
            )

        # Fiscal Year Tab
        if self.request.user.has_perm("horilla_core.view_fiscalyear"):
            tabs.append(
                {
                    "title": _("Fiscal Year"),
                    "url": reverse_lazy("horilla_core:company_fiscal_year_tab"),
                    "target": "fiscal-year-view-content",
                    "id": "fiscal-year-view",
                }
            )

        # Business Hours Tab
        if self.request.user.has_perm("horilla_core.view_businesshour"):
            tabs.append(
                {
                    "title": _("Business Hours"),
                    "url": reverse_lazy("horilla_core:business_hour_view"),
                    "target": "business-hour-content",
                    "id": "business-hour-view",
                }
            )

        # Holidays Tab
        if self.request.user.has_perm("horilla_core.view_holiday"):
            tabs.append(
                {
                    "title": _("Holidays"),
                    "url": reverse_lazy("horilla_core:holiday_view"),
                    "target": "holidays-view-content",
                    "id": "holidays-view",
                }
            )

        # Currencies Tab
        if self.request.user.has_perm("horilla_core.view_multiplecurrency"):
            tabs.append(
                {
                    "title": _("Currencies"),
                    "url": reverse_lazy("horilla_core:multiple_currency"),
                    "target": "currency-view-content",
                    "id": "currency-view",
                }
            )

        # Recycle Bin Policy Tab
        if self.request.user.has_perm("horilla_core.view_recyclebinpolicy"):
            tabs.append(
                {
                    "title": _("Recycle Bin Policy"),
                    "url": reverse_lazy("horilla_core:recycle_bin_policy_view"),
                    "target": "recycle-view-content",
                    "id": "recycle-view",
                }
            )

        return tabs


class SettingView(LoginRequiredMixin, TemplateView):
    """
    TemplateView for settings page.
    """

    template_name = "settings/settings.html"


class MySettingView(LoginRequiredMixin, TemplateView):
    """
    TemplateView for settings page.
    """

    template_name = "settings/my_settings.html"


class ConmpanyInformationView(LoginRequiredMixin, TemplateView):
    """
    TemplateView for company information settings page.
    """

    template_name = "settings/company_information.html"

    def get_context_data(self, **kwargs):
        """
        Get context data for company information view.
        """
        context = super().get_context_data(**kwargs)
        company = getattr(self.request, "active_company", None)
        context["has_company"] = bool(company)
        return context


@method_decorator(htmx_required, name="dispatch")
class CompanyMultiFormView(LoginRequiredMixin, HorillaMultiStepFormView):
    """compnay Create/Update View"""

    form_class = CompanyMultistepFormClass
    model = Company
    view_id = "company-form-view"
    save_and_new = False
    single_step_url_name = {
        "create": "horilla_core:create_company",
        "edit": "horilla_core:edit_company",
    }

    def get_signal_kwargs(self):
        """
        Extension point: Override this method to pass additional data to signal.
        Clients can add custom data without modifying source code.
        """
        return {}

    @cached_property
    def form_url(self):
        """Form URL for company"""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "horilla_core:edit_company_multi_step", kwargs={"pk": pk}
            )
        return reverse_lazy("horilla_core:create_company_multi_step")

    def form_valid(self, form):
        """
        Handle valid form submission.
        """

        step = self.get_initial_step()

        if step < self.total_steps:
            return super().form_valid(form)

        response = super().form_valid(form)
        custom_kwargs = self.get_signal_kwargs()
        signal_kwargs = {
            "instance": self.object,
            "request": self.request,
            "view": self,
            "is_new": not self.kwargs.get("pk"),
            **custom_kwargs,
        }
        responses = company_created.send(sender=self.__class__, **signal_kwargs)

        for _receiver, response in responses:
            if isinstance(response, HttpResponse):
                wrapped_response = HttpResponse(
                    f'<div id="{self.view_id}-container">{response.content.decode()}</div>'
                )
                return wrapped_response

        if self.request.GET.get("details") == "true":
            return HttpResponse(
                "<script>$('#reloadButton').click();closeModal();</script>"
            )

        branches_view_url = reverse_lazy("horilla_core:branches_view")
        response_html = (
            f"<span "
            f'hx-trigger="load" '
            f'hx-get="{branches_view_url}" '
            f'hx-select="#branches-view" '
            f'hx-target="#branches-view" '
            f'hx-swap="outerHTML" '
            f'hx-on::after-request="closeModal();"'
            f'hx-select-oob="#dropdown-companies">'
            f"</span>"
        )
        return HttpResponse(mark_safe(response_html))

    step_titles = {
        "1": _("Basic Information"),
        "2": _("Business Details"),
        "3": _("Location & Locale"),
        "4": _("Preferences"),
    }

    def get_form_kwargs(self):
        """
        Get form kwargs for company multi-step form.
        """
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs


@method_decorator(htmx_required, name="dispatch")
class CompanyFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    compnay Create/Update View
    """

    model = Company
    view_id = "company-form-view"
    form_class = CompanyFormClassSingle
    save_and_new = False

    def get_signal_kwargs(self):
        """
        Extension point: Override this method to pass additional data to signal.
        Clients can add custom data without modifying source code.
        """
        return {}

    multi_step_url_name = {
        "create": "horilla_core:create_company_multi_step",
        "edit": "horilla_core:edit_company_multi_step",
    }

    @cached_property
    def form_url(self):
        """Form URL for company"""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("horilla_core:edit_company", kwargs={"pk": pk})
        return reverse_lazy("horilla_core:create_company")

    def form_valid(self, form):
        """
        Handle valid form submission.
        """
        super().form_valid(form)
        custom_kwargs = self.get_signal_kwargs()
        signal_kwargs = {
            "instance": self.object,
            "request": self.request,
            "view": self,
            "is_new": not self.kwargs.get("pk"),
            **custom_kwargs,  # Add any custom kwargs from override
        }
        responses = company_created.send(sender=self.__class__, **signal_kwargs)

        for _receiver, response in responses:
            if isinstance(response, HttpResponse):
                wrapped_response = HttpResponse(
                    f'<div id="{self.view_id}-container">{response.content.decode()}</div>'
                )
                return wrapped_response

        if self.request.GET.get("details") == "true":
            return HttpResponse(
                "<script>$('#reloadButton').click();closeModal();</script>"
            )
        branches_view_url = reverse_lazy("horilla_core:branches_view")

        response_html = (
            f"<span "
            f'hx-trigger="load" '
            f'hx-get="{branches_view_url}" '
            f'hx-select="#branches-view" '
            f'hx-target="#branches-view" '
            f'hx-swap="outerHTML" '
            f'hx-on::after-request="closeModal();"'
            f'hx-select-oob="#dropdown-companies">'
            f"</span>"
        )
        return HttpResponse(mark_safe(response_html))


@method_decorator(
    permission_required_or_denied("horilla_core.can_switch_company"), name="dispatch"
)
class SwitchCompanyView(LoginRequiredMixin, View):
    """
    View to switch active company for the user.
    """

    def post(self, request, company_id):
        """
        Switch the active company for the user.
        """
        if request.user.is_authenticated and (
            request.user.has_perm("horilla_core.can_switch_company")
            or request.user.company_id == company_id
        ):
            request.session["active_company_id"] = company_id
        return redirect(request.META.get("HTTP_REFERER", "/"))


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.view_company"), name="dispatch"
)
class CompanyDetailsTab(LoginRequiredMixin, TemplateView):
    """
    TemplateView for company details tab.
    """

    template_name = "settings/company_details_tab.html"

    def get_context_data(self, **kwargs):
        """
        Get context data for company details tab.
        """
        context = super().get_context_data(**kwargs)
        company = getattr(self.request, "active_company", None)
        if company:
            obj = company
        else:
            obj = self.request.user.company
        context["obj"] = obj
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.view_company"), name="dispatch"
)
class CompanyFiscalYearTab(LoginRequiredMixin, TemplateView):
    """
    TemplateView for fiscal year tab.
    """

    template_name = "settings/fiscal_year.html"

    def get_context_data(self, **kwargs):
        """
        Get context data for fiscal year tab.
        """
        context = super().get_context_data(**kwargs)
        company = getattr(self.request, "active_company", None)
        if company:
            cmp = company
        else:
            cmp = self.request.user.company
        if not company:
            context["has_company"] = False
            return context
        obj = cmp.fiscalyear_set.first() if cmp.fiscalyear_set.exists() else None
        start_date = None
        if obj:
            current_fy_instance = obj.year_instances.filter(is_current=True).first()
            if current_fy_instance:
                start_date = current_fy_instance.start_date
        context["obj"] = obj
        context["start_date"] = start_date
        context["has_company"] = True
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.view_holiday"), name="dispatch"
)
class HolidayView(LoginRequiredMixin, TemplateView):
    """
    TemplateView for holiday view.
    """

    template_name = "settings/holiday.html"


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.view_holiday"), name="dispatch"
)
class HolidayListView(LoginRequiredMixin, HorillaListView):
    """
    List View for holiday list.
    """

    model = Holiday
    view_id = "holiday-list-view"
    table_width = False
    bulk_select_option = False
    clear_session_button_enabled = False
    search_url = reverse_lazy("horilla_core:holiday_list_view")
    store_ordered_ids = True

    columns = ["name", "start_date", "end_date", "is_recurring"]

    @cached_property
    def col_attrs(self):
        """
        Get the column attributes for the list view.
        """
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = self.request.session.get(self.ordered_ids_key, [])
        attrs = {}
        if self.request.user.has_perm("horilla_core.view_holiday"):
            attrs = {
                "hx-get": f"{{get_detail_url}}?instance_ids={query_string}",
                "hx-target": "#detailModalBox",
                "hx-swap": "innerHTML",
                "hx-push-url": "false",
                "hx-on:click": "openDetailModal();",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4 flex gap-4",
            "permission": "horilla_core.change_holiday",
            "attrs": """
                hx-get="{get_edit_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
            """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "horilla_core.delete_holiday",
            "attrs": """
                hx-post="{get_delete_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                hx-vals='{{"check_dependencies": "false"}}'
                onclick="openModal()"
            """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.delete_holiday", modal=True),
    name="dispatch",
)
class HolidayDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete View for Holiday
    """

    model = Holiday

    def get_post_delete_response(self):
        """
        Get the response after deleting a holiday.
        """

        return HttpResponse(
            "<script>$('#reloadButton').click();closeDeleteModeModal();</script>"
        )


@method_decorator(htmx_required, name="dispatch")
class HolidayFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Holiday Create/Update View
    """

    model = Holiday
    form_class = HolidayForm
    view_id = "holiday-form-view"
    form_title = "Holiday Form"
    # hidden_fields = ["company"]
    full_width_fields = ["name"]

    @cached_property
    def form_url(self):
        """Form URL for holiday"""

        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("horilla_core:holiday_update_form", kwargs={"pk": pk})
        return reverse_lazy("horilla_core:holiday_create_form")

    def get_initial(self):
        """
        Get initial data for holiday form.
        """

        initial = super().get_initial()

        toggle = self.request.GET.get("toggle_all_users")

        if toggle == "true":
            current = self.request.GET.get("all_users", "").lower()
            current_recurring = self.request.GET.get("is_recurring", "").lower()

            initial["all_users"] = current in ["true", "on", "1"]
            initial["is_recurring"] = current_recurring in ["true", "on", "1"]
            initial["frequency"] = self.request.GET.get("frequency", "")
            initial["monthly_repeat_type"] = self.request.GET.get(
                "monthly_repeat_type", ""
            )
            initial["yearly_repeat_type"] = self.request.GET.get(
                "yearly_repeat_type", ""
            )

        elif hasattr(self, "object") and self.object:
            initial["all_users"] = self.object.all_users
            initial["is_recurring"] = self.object.is_recurring
            initial["frequency"] = getattr(self.object, "frequency", "")
            initial["monthly_repeat_type"] = getattr(
                self.object, "monthly_repeat_type", ""
            )
            initial["yearly_repeat_type"] = getattr(
                self.object, "yearly_repeat_type", ""
            )

        else:
            initial["all_users"] = False
            initial["is_recurring"] = False
            initial["frequency"] = ""
            initial["monthly_repeat_type"] = ""
            initial["yearly_repeat_type"] = ""

        initial.update(self.request.GET.dict())

        return initial

    def form_invalid(self, form):
        """
        Handle invalid form submission.
        """
        response = super().form_invalid(form)
        return response


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.view_holiday"), name="dispatch"
)
class HolidayDetailView(LoginRequiredMixin, HorillaModalDetailView):
    """
    detail view of page
    """

    model = Holiday
    title = _("Details")
    header = {
        "title": "name",
        "subtitle": "",
        "avatar": "get_avatar",
    }

    body = [
        (_("Holiday Start Date"), "start_date"),
        (_("Holiday End Date"), "end_date"),
        (_("Specific Users"), "specific_users_enable"),
        (_("Recurring"), "is_recurring_holiday"),
    ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit_white.svg",
            "img_class": "w-3 h-3 flex gap-4 filter brightness-0 invert",
            "permission": "horilla_core.change_holiday",
            "attrs": """
                class="w-24 justify-center px-4 py-2 bg-primary-600 text-white rounded-md text-xs flex items-center gap-2 hover:bg-primary-800 transition duration-300 disabled:cursor-not-allowed"
                hx-get="{get_edit_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal();"
            """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-3 h-3 flex gap-4 brightness-0 saturate-100",
            "image_style": "filter: invert(27%) sepia(51%) saturate(2878%) hue-rotate(346deg) brightness(104%) contrast(97%)",
            "permission": "horilla_core.delete_holiday",
            "attrs": """
                    class="w-24 justify-center px-4 py-2 bg-[white] rounded-md text-xs flex items-center gap-2 border border-primary-500 hover:border-primary-600 transition duration-300 disabled:cursor-not-allowed text-primary-600"
                    hx-post="{get_delete_url}"
                    hx-target="#deleteModeBox"
                    hx-swap="innerHTML"
                    hx-trigger="confirmed"
                    hx-on:click="hxConfirm(this,'Are you sure you want to delete this holiday?')"
                    hx-on::after-request="closeDetailModal();"
                """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.view_multiplecurrency"), name="dispatch"
)
class CompanyMultipleCurrency(LoginRequiredMixin, TemplateView):
    """
    TemplateView for multiple currency view.
    """

    template_name = "settings/multiple_currency.html"

    def get_context_data(self, **kwargs):
        """
        Get context data for multiple currency view.
        """
        context = super().get_context_data(**kwargs)
        company = getattr(self.request, "active_company", None)
        if company:
            cmp = company
        else:
            cmp = self.request.user.company
        context["has_company"] = bool(cmp)
        if not cmp:
            return context
        currencies = MultipleCurrency.objects.filter(company=cmp)
        obj = currencies.filter(company=cmp, is_default=True).first()
        context["obj"] = obj
        context["cmp"] = cmp
        context["currencies"] = currencies
        start_dates = (
            DatedConversionRate.objects.values_list("start_date", flat=True)
            .distinct()
            .order_by("start_date")
        )
        date_ranges = []
        current_date = datetime.now().date()
        selected_start_date = None

        for i, start_date in enumerate(start_dates):
            end_date = None
            if i < len(start_dates) - 1:
                end_date = start_dates[i + 1] - timedelta(days=1)
                date_ranges.append(
                    {
                        "start_date": start_date,
                        "end_date": end_date,
                        "display": f"{start_date.strftime('%d-%m-%Y')} to {end_date.strftime('%d-%m-%Y')}",
                    }
                )
                if start_date <= current_date <= end_date:
                    selected_start_date = start_date
            else:
                date_ranges.append(
                    {
                        "start_date": start_date,
                        "end_date": None,
                        "display": f"{start_date.strftime('%d-%m-%Y')} and After",
                    }
                )
                if start_date <= current_date:
                    selected_start_date = start_date

        context["date_ranges"] = date_ranges
        context["selected_start_date"] = selected_start_date
        return context

    def post(self, request, *args, **kwargs):
        """Handle HTMX toggle for multiple currency activation"""
        company = getattr(request, "active_company", None)
        if company:
            cmp = company
        else:
            cmp = request.user.company

        if not request.user.has_perm("horilla_core.change_company"):
            return render(request, "error/403.html")

        cmp.activate_multiple_currencies = not cmp.activate_multiple_currencies
        cmp.save()
        context = self.get_context_data(**kwargs)
        return render(request, self.template_name, context)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.view_businesshour"), name="dispatch"
)
class BusinessHourView(LoginRequiredMixin, TemplateView):
    """
    TemplateView for business hour view.
    """

    template_name = "settings/business_hour/business_hour.html"


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.view_businesshour"), name="dispatch"
)
class BusinessHourListView(LoginRequiredMixin, HorillaListView):
    """
    List View for business hour.
    """

    model = BusinessHour
    view_id = "business-hour-list-view"
    table_width = False
    bulk_select_option = False
    clear_session_button_enabled = False
    search_url = reverse_lazy("horilla_core:business_hour_list_view")
    store_ordered_ids = True

    columns = [
        "name",
        "time_zone",
        "business_hour_type",
        "week_start_day",
        (_("Default Business Hour"), "is_default_hour"),
    ]

    @cached_property
    def col_attrs(self):
        """
        Get the column attributes for the list view.
        """
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = self.request.session.get(self.ordered_ids_key, [])
        attrs = {}
        attrs = {
            "hx-get": f"{{get_detail_url}}?instance_ids={query_string}",
            "hx-target": "#detailModalBox",
            "hx-swap": "innerHTML",
            "hx-push-url": "false",
            "hx-on:click": "openDetailModal();",
            "style": "cursor:pointer",
            "class": "hover:text-primary-600",
        }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4 flex gap-4",
            "permission": "horilla_core.change_businesshour",
            "attrs": """
                hx-get="{get_edit_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
            """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "horilla_core.delete_businesshour",
            "attrs": """
                    hx-post="{get_delete_url}"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    hx-trigger="click"
                    hx-vals='{{"check_dependencies": "false"}}'
                    onclick="openModal()"
                """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
class BusinessHourFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Business Hour Create/Update View
    """

    model = BusinessHour
    form_class = BusinessHourForm
    view_id = "business-hour-form-view"
    form_title = "Business Hour Form"
    hidden_fields = ["company"]

    @cached_property
    def form_url(self):
        """Form URL for business hour"""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "horilla_core:business_hour_update_form", kwargs={"pk": pk}
            )
        return reverse_lazy("horilla_core:business_hour_create_form")

    def get_initial(self):
        """
        Get initial data for business hour form.
        """
        initial = super().get_initial()
        toggle = self.request.GET.get("toggle_data")
        company = getattr(self.request, "active_company", None)
        initial["company"] = company
        if toggle == "true":
            initial["business_hour_type"] = self.request.GET.get(
                "business_hour_type", ""
            )
            initial["timing_type"] = self.request.GET.get("timing_type", "")

        elif hasattr(self, "object") and self.object:
            initial["business_hour_type"] = getattr(
                self.object, "business_hour_type", ""
            )
            initial["timing_type"] = getattr(self.object, "timing_type", "")

        else:
            initial["business_hour_type"] = ""
            initial["timing_type"] = ""

        initial.update(self.request.GET.dict())
        return initial


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.delete_businesshour", modal=True),
    name="dispatch",
)
class BusinessHourDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete View for Business Hour
    """

    model = BusinessHour

    def get_post_delete_response(self):
        """
        Get the response after deleting a business hour.
        """
        return HttpResponse(
            "<script>$('#reloadButton').click();closeDeleteModeModal();</script>"
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("horilla_core.view_businesshour"), name="dispatch"
)
class BusinessHourDetailView(LoginRequiredMixin, HorillaModalDetailView):
    """
    detail view of page
    """

    model = BusinessHour
    title = _("Details")
    header = {
        "title": "name",
        "subtitle": "",
        "avatar": "get_avatar",
    }

    body = [
        (_("Time Zone"), "time_zone"),
        (_("Hour Type"), "get_business_hour_type_display"),
        (_("Is Default"), "is_default_hour"),
        (_("Week Starts On"), "get_week_start_day_display"),
        (_("Business Days"), "get_formatted_week_days"),
    ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit_white.svg",
            "img_class": "w-3 h-3 flex gap-4 filter brightness-0 invert",
            "permission": "horilla_core.change_businesshour",
            "attrs": """
                class="w-24 justify-center px-4 py-2 bg-primary-600 text-white rounded-md text-xs flex items-center gap-2 hover:bg-primary-800 transition duration-300 disabled:cursor-not-allowed"
                hx-get="{get_edit_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal();"
            """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-3 h-3 flex gap-4 brightness-0 saturate-100",
            "image_style": "filter: invert(27%) sepia(51%) saturate(2878%) hue-rotate(346deg) brightness(104%) contrast(97%)",
            "permission": "horilla_core.delete_businesshour",
            "attrs": """
                    class="w-24 justify-center px-4 py-2 bg-[white] rounded-md text-xs flex items-center gap-2 border border-primary-500 hover:border-primary-600 transition duration-300 disabled:cursor-not-allowed text-primary-600"
                    hx-post="{get_delete_url}"
                    hx-target="#deleteModeBox"
                    hx-swap="innerHTML"
                    hx-trigger="confirmed"
                    hx-on:click="hxConfirm(this,'Are you sure you want to delete this holiday?')"
                    hx-on::after-request="closeDetailModal();"
                    """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
class GetCountrySubdivisionsView(LoginRequiredMixin, View):
    """
    View to get country subdivisions (states/provinces) based on country code.
    """

    def get(self, request, *args, **kwargs):
        """
        Get HTML options for country subdivisions based on country code.

        Args:
            request: The HTTP request object.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Returns:
            HttpResponse: HTML string containing option elements for subdivisions.
        """
        country_code = request.GET.get("country")
        options = '<option value="">Select State</option>'

        if country_code:
            subdivisions = pycountry.subdivisions.get(country_code=country_code.upper())
            for subdivision in subdivisions:
                options += (
                    f'<option value="{subdivision.code}">{subdivision.name}</option>'
                )

        return HttpResponse(options)


class RolesView(LoginRequiredMixin, TemplateView):
    """
    TemplateView for role settings page.
    """

    template_name = "role/role.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        roles = Role.objects.all()

        def build_role_tree(parent_role=None):
            """Recursively build role hierarchy"""
            children = roles.filter(parent_role=parent_role)
            role_tree = []

            for role in children:
                user_count = role.users.count()
                role_dict = {
                    "id": role.id,
                    "name": role.role_name,
                    "description": getattr(role, "description", ""),
                    "user_count": user_count,
                    "children": build_role_tree(role),
                }
                role_tree.append(role_dict)

            return role_tree

        roles_data = build_role_tree()

        context["roles_data"] = roles_data
        context["roles_count"] = roles.count()
        return context


class FaviconRedirectView(RedirectView):
    """Redirect to the configured favicon."""

    branding = load_branding()
    favicon_path = branding.get("FAVICON_PATH", "favicon.ico")
    url = staticfiles_storage.url(favicon_path)
