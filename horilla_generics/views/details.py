"""
Generic detail view for displaying individual model instances, with support for dynamic field visibility, permissions,
pipeline stages, badges, and breadcrumbs. This view can be subclassed for specific models to customize the displayed fields, actions, and pipeline behavior.
"""

# Standard library
import logging
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

# Django / third-party imports
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.db.models import ForeignKey
from django.template.loader import render_to_string
from django.views.generic import DetailView

# First-party (Horilla)
from horilla.apps import apps
from horilla.core.exceptions import FieldDoesNotExist, ValidationError
from horilla.http import Http404, HttpNotFound, HttpResponse, QueryDict, RefreshResponse
from horilla.shortcuts import redirect, render
from horilla.urls import resolve, reverse, reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# First-party / Horilla apps
from horilla_utils.methods import closest_numbers, get_section_info_for_model
from horilla_utils.middlewares import _thread_local

logger = logging.getLogger(__name__)


class HorillaDetailView(DetailView):
    """Generic detail view for displaying individual model instances."""

    template_name = "detail_view.html"
    context_object_name = "obj"
    body: list = []
    header_fields: list = (
        []
    )  # Fields shown in header (e.g. title). If empty, first body field is used.
    base_excluded_fields = [
        "id",
        "created_at",
        "additional_info",
        "updated_at",
        "history",
        "is_active",
        "created_by",
        "updated_by",
    ]
    excluded_fields = (
        []
    )  # Subclass: add more field names to exclude (extends base_excluded_fields).
    split_excluded_fields: list = (
        []
    )  # Optional extra fields to exclude only in split layout/detail section.
    pipeline_field = ""
    breadcrumbs = []
    actions = []
    tab_url: str = ""
    final_stage_action = {}
    badge: list = (
        []
    )  # List of badge configurations: [{"condition": callable, "label": str, "class": str}, ...]

    _view_registry = {}

    def __init_subclass__(cls, **kwargs):
        """
        Automatically register child classes with their models.
        This allows the parent to find the correct child class dynamically.
        """
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "model") and cls.model:
            HorillaDetailView._view_registry[cls.model] = cls

    def dispatch(self, request, *args, **kwargs):
        """Resolve model and object, check view/own permissions, then dispatch."""
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        try:
            model_name = request.POST.get("model_name") or request.GET.get("model_name")
            app_label = request.POST.get("app_label") or request.GET.get("app_label")

            if model_name and app_label:
                self.model = apps.get_model(app_label=app_label, model_name=model_name)

            self.object = self.get_object()
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                messages.error(request, e)
                return RefreshResponse(request)
            raise HttpNotFound(e)

        app = self.model._meta.app_label
        model = self.model._meta.model_name
        user = request.user
        obj = self.object

        view_perm = f"{app}.view_{model}"

        OWNER_FIELDS = getattr(self.model, "OWNER_FIELDS", ["owner"])

        is_owner = False
        for field in OWNER_FIELDS:
            try:
                v = getattr(obj, field, None)
                if v:
                    if hasattr(v, "all"):
                        if user in v.all():
                            is_owner = True
                            break
                    elif v == user:
                        is_owner = True
                        break
            except Exception:
                pass

        own_view_perm = f"{app}.view_own_{model}"

        allowed = user.has_perm(view_perm) or (
            is_owner and user.has_perm(own_view_perm)
        )
        if not allowed:
            return render(request, "403.html")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        """Redirect unauthenticated users to login; otherwise delegate to parent get."""
        if not self.request.user.is_authenticated:
            login_url = f"{reverse_lazy('horilla_core:login')}?next={request.path}"
            return redirect(login_url)
        return super().get(request, *args, **kwargs)

    def get_template_names(self):
        """Use fragment template when layout=split for split-view right panel."""
        if self.request.GET.get("layout") == "split":
            return ["detail_view_split_fragment.html"]
        return super().get_template_names()

    def get_queryset(self):
        """Return the queryset for the detail view; require model to be set."""
        if not self.model:
            raise HttpNotFound("Model not found")
        return super().get_queryset()

    def _normalize_field_list(self, field_list, exclude_set):
        """Normalize a list of fields to (verbose_name, field_name) and filter by permissions and excluded_fields.
        Always resolves verbose_name from the model so translations work in the current request language.
        """
        from horilla_core.utils import get_field_permissions_for_model

        if not field_list:
            return []
        field_permissions = get_field_permissions_for_model(
            self.request.user, self.model
        )
        instance = self.model()
        result = []
        for field in field_list:
            field_name = (
                field[1]
                if isinstance(field, (list, tuple)) and len(field) >= 2
                else field
            )
            if field_name in exclude_set:
                continue
            field_perm = field_permissions.get(field_name, "readwrite")
            if field_perm == "hidden":
                continue
            try:
                model_field = instance._meta.get_field(field_name)
                result.append((model_field.verbose_name, field_name))
            except FieldDoesNotExist:
                pass
        return result

    def get_excluded_fields(self):
        """Return effective excluded fields: base list plus any extra from subclasses."""
        base = list(self.base_excluded_fields)
        extra = [f for f in (self.excluded_fields or []) if f not in base]
        return base + extra

    def get_header_fields(self):
        """Return normalized (verbose_name, field_name) list for header. Excluded fields are omitted."""
        excluded_set = set(self.get_excluded_fields())
        if self.header_fields:
            return self._normalize_field_list(self.header_fields, excluded_set)
        full_body = self._normalize_field_list(self.body, excluded_set)
        return [full_body[0]] if full_body else []

    def get_detail_section_body(self):
        """
        Return body list for split-view / detail section: all model fields
        excluding base_excluded_fields, excluded_fields, split_excluded_fields (for split layout),
        and pipeline_field
        (same logic as HorillaDetailSectionView.get_default_body).
        """
        excluded = list(self.get_excluded_fields())
        if self.request.GET.get("layout") == "split":
            for field in getattr(self, "split_excluded_fields", []) or []:
                if field not in excluded:
                    excluded.append(field)
        effective_pf = self._get_effective_pipeline_field()
        if effective_pf:
            excluded.append(effective_pf)
        include_fields = getattr(self, "include_fields", None)
        if include_fields:
            return [
                (f.verbose_name, f.name)
                for f in self.model._meta.get_fields()
                if f.name in include_fields
                and f.name not in excluded
                and hasattr(f, "verbose_name")
            ]
        return [
            (f.verbose_name, f.name)
            for f in self.model._meta.get_fields()
            if f.name not in excluded and hasattr(f, "verbose_name")
        ]

    def get_body(self):
        """Return normalized (verbose_name, field_name) list for details grid. Excluded fields are omitted."""
        from horilla_core.models import DetailFieldVisibility

        excluded_set = set(self.get_excluded_fields())
        url = resolve(self.request.path)
        url_name = url.url_name if url else ""
        visibility = DetailFieldVisibility.all_objects.filter(
            user=self.request.user,
            app_label=self.model._meta.app_label,
            model_name=self.model._meta.model_name,
            url_name=url_name,
        ).first()
        if visibility and visibility.header_fields:
            return self._normalize_field_list(visibility.header_fields, excluded_set)
        full_body = self._normalize_field_list(self.body, excluded_set)
        if self.header_fields:
            return full_body
        # Return full body so body[0]=title (heading), body[1:]=first_name,last_name... (grid)
        return full_body

    def check_update_permission(self):
        """
        Check if the current user has permission to update the pipeline field.
        Returns True if user has permission, False otherwise.
        """
        user = self.request.user
        current_obj = self.get_object()
        model_name = self.model._meta.model_name
        app_label = self.model._meta.app_label

        is_owner = False
        owner_fields = getattr(self.model, "OWNER_FIELDS", [])

        for owner_field in owner_fields:
            try:
                field_value = getattr(current_obj, owner_field, None)
                if field_value:
                    # Handle ManyToMany fields
                    if hasattr(field_value, "all"):
                        if user in field_value.all():
                            is_owner = True
                            break
                    # Handle ForeignKey fields
                    elif field_value == user:
                        is_owner = True
                        break
            except Exception:
                continue

        # Check change_own permission if user is owner
        if is_owner:
            change_own_perm = f"{app_label}.change_own_{model_name}"
            if user.has_perm(change_own_perm):
                return True

        # Check regular change permission
        change_perm = f"{app_label}.change_{model_name}"
        if user.has_perm(change_perm):
            return True

        return False

    def _get_effective_pipeline_field(self):
        """
        Return pipeline_field only if the user has permission to see it (not "Don't Show").
        Returns None if the field is hidden for the current user.
        """
        from horilla_core.utils import filter_hidden_fields

        if not self.pipeline_field:
            return None
        visible = filter_hidden_fields(
            self.request.user, self.model, [self.pipeline_field]
        )
        return self.pipeline_field if self.pipeline_field in visible else None

    def get_pipeline_choices(self):
        """
        Generate pipeline data for the specified pipeline_field.
        Returns a list of tuples: (display_name, value, is_completed, is_current).
        - For choice fields: Use choices defined in the model.
        - For foreign keys: Use related objects, ordered by the 'order' field.
        - is_completed: True if the stage's order is < the current value's order.
        - is_current: True if this is the current stage.
        """
        if not self.pipeline_field:
            return []
        try:
            obj = self.get_object()
        except Http404:
            return render(self.request, "403.html")
        field = self.model._meta.get_field(self.pipeline_field)
        current_value = getattr(obj, self.pipeline_field)

        pipeline = []
        if hasattr(field, "choices") and field.choices:
            current_choice_index = None
            for i, (value, display_name) in enumerate(field.choices):
                if value == current_value:
                    current_choice_index = i
                    break

            for i, (value, display_name) in enumerate(field.choices):
                is_completed = (
                    current_choice_index is not None and i < current_choice_index
                )
                is_current = value == current_value
                is_final = False
                pipeline.append(
                    (display_name, value, is_completed, is_current, is_final)
                )

        elif isinstance(field, ForeignKey):
            related_model = field.related_model
            order_field = None
            try:
                order_field = related_model._meta.get_field("order")
            except Exception:
                pass
            queryset = related_model.objects.all()

            if (
                hasattr(related_model, "company")
                and hasattr(obj, "company")
                and obj.company
            ):
                queryset = queryset.filter(company=obj.company)

            if order_field:
                queryset = queryset.order_by("order")

            current_order = (
                getattr(current_value, "order", None) if current_value else None
            )
            current_id = current_value.id if current_value else None

            for related_obj in queryset:
                is_completed = False
                is_current = related_obj.id == current_id
                is_final = getattr(related_obj, "is_final", False)
                if current_order is not None:
                    related_order = getattr(related_obj, "order", None)
                    is_completed = (
                        related_order is not None and related_order < current_order
                    )
                pipeline.append(
                    (
                        str(related_obj),
                        related_obj.id,
                        is_completed,
                        is_current,
                        is_final,
                    )
                )
        else:
            return []

        return pipeline

    def get_badges(self):
        """
        Get badges to display for the current object.
        Returns a list of badge dictionaries with 'label' and 'class' keys.
        Each badge in self.badge should have:
        - condition: A callable that takes the object and returns True if badge should show
        - label: The text to display on the badge
        - class: CSS classes for styling the badge
        - icon: (optional) FontAwesome icon class (e.g., "fa-solid fa-check")
        - icon_class: (optional) CSS classes for the icon
        - icon_bg_class: (optional) CSS classes for the icon background circle
        """
        badges = []
        if not self.badge:
            return badges

        obj = self.get_object()
        for badge_config in self.badge:
            try:
                condition = badge_config.get("condition")
                badge_data = {
                    "label": badge_config.get("label", ""),
                    "class": badge_config.get("class", ""),
                }
                # Include icon fields if present
                if "icon" in badge_config:
                    badge_data["icon"] = badge_config.get("icon")
                if "icon_class" in badge_config:
                    badge_data["icon_class"] = badge_config.get("icon_class")
                if "icon_bg_class" in badge_config:
                    badge_data["icon_bg_class"] = badge_config.get("icon_bg_class")

                if condition and callable(condition):
                    if condition(obj):
                        badges.append(badge_data)
                elif condition is None:
                    # If no condition, always show
                    badges.append(badge_data)
            except Exception as e:
                logger.warning("Error evaluating badge condition: %s", str(e))
                continue

        return badges

    def _get_details_section_url_for_fields(self, object_id):
        """
        Infer the details section URL name from the tab view (when tab_url is set)
        so the Fields modal uses the same visible/excluded fields as the Details tab.
        Returns the URL name (e.g. "leads:leads_details_tab") or None.
        """
        from types import SimpleNamespace

        tab_url = getattr(self, "tab_url", None)
        if not tab_url:
            return None
        try:
            path = str(tab_url)
            resolved = resolve(path)
            tab_view_class = getattr(resolved.func, "view_class", None)
            if not tab_view_class:
                return None
            # Tab view subclasses set self.urls in __init__ using request from _thread_local.
            # Minimal request must have .GET and .user so HorillaDetailTabView.__init__ does not raise.
            q = QueryDict(mutable=True)
            q.setlist("object_id", [str(object_id)])
            req = SimpleNamespace(GET=q, user=getattr(self.request, "user", None))
            saved_request = getattr(_thread_local, "request", None)
            try:
                _thread_local.request = req
                view_inst = tab_view_class()
                return (getattr(view_inst, "urls", None) or {}).get("details")
            finally:
                _thread_local.request = saved_request
        except Exception:
            return None

    def get_context_data(self, **kwargs):
        """Add header_fields, body, pipeline_choices, badges, and permissions to context."""
        context = super().get_context_data(**kwargs)
        context["header_fields"] = self.get_header_fields()
        current_obj = self.get_object()
        # Support split layout flag coming from both GET (initial load)
        # and POST (e.g. pipeline updates via HTMX hx-vals)
        is_split_layout = (
            self.request.GET.get("layout") == "split"
            or self.request.POST.get("layout") == "split"
        )
        if is_split_layout:
            context["body"] = self.get_detail_section_body()
            context["split_detail_url"] = (
                current_obj.get_detail_url()
                if hasattr(current_obj, "get_detail_url")
                else None
            )
        else:
            context["body"] = self.get_body()
        context["pipeline_choices"] = self.get_pipeline_choices()
        current_id = current_obj.id
        context["tab_url"] = self.tab_url
        context["badges"] = self.get_badges()
        from horilla_core.utils import get_field_permissions_for_model

        field_permissions = get_field_permissions_for_model(
            self.request.user, self.model
        )
        context["can_update"] = self.check_update_permission()
        context["field_permissions"] = field_permissions
        if hasattr(self, "final_stage_action"):
            final_stage = self.final_stage_action
            if callable(final_stage):
                context["final_stage_action"] = final_stage()
            else:
                context["final_stage_action"] = final_stage
        else:
            context["final_stage_action"] = self.final_stage_action

        # Get custom pipeline colors if method exists
        if hasattr(self, "get_pipeline_custom_colors"):
            custom_colors = self.get_pipeline_custom_colors()
            if custom_colors:
                context["pipeline_custom_bg_color"] = custom_colors.get("bg_color")
                context["pipeline_custom_text_color"] = custom_colors.get("text_color")
                context["pipeline_custom_hover_color"] = custom_colors.get(
                    "hover_color"
                )

        session_key = f"list_view_queryset_ids_{self.model._meta.model_name}"

        queryset_ids = self.request.session.get(session_key, [])
        if not queryset_ids:
            from horilla_generics.views.list import HorillaListView

            list_view = HorillaListView()
            list_view.request = self.request
            list_view.model = self.model
            queryset = list_view.get_queryset()
            queryset_ids = list(queryset.values_list("id", flat=True))
            self.request.session["list_view_queryset_ids"] = queryset_ids
        try:
            current_index = queryset_ids.index(current_id)
        except ValueError:
            current_index = -1
        context["has_previous"] = current_index > 0
        context["has_next"] = current_index < len(queryset_ids) - 1
        context["previous_id"] = (
            queryset_ids[current_index - 1] if context["has_previous"] else None
        )
        context["next_id"] = (
            queryset_ids[current_index + 1] if context["has_next"] else None
        )
        url = resolve(self.request.path)
        context["url_name"] = url.url_name
        context["app_label"] = self.model._meta.app_label

        detail_actions = list(self.actions) if self.actions else []
        if is_split_layout and context.get("split_detail_url"):
            detail_actions = detail_actions + [
                {
                    "action": _("View full detail"),
                    "src": "assets/icons/eye1.svg",
                    "img_class": "w-4 h-4",
                    "attrs": (
                        f'hx-get="{context["split_detail_url"]}" '
                        'hx-target="#mainContent" hx-select="#mainContent" '
                        'hx-swap="outerHTML" hx-push-url="true" '
                        'hx-indicator="#loading-indicator"'
                    ),
                }
            ]
        if self.tab_url:
            change_fields_url = (
                f"{reverse('horilla_generics:detail_field_selector')}"
                f"?app_label={self.model._meta.app_label}&model_name={self.model._meta.model_name}&url_name={url.url_name}&pk={current_id}"
            )
            details_section_url = self._get_details_section_url_for_fields(current_id)
            if details_section_url:
                change_fields_url += (
                    f"&details_section_url={quote(details_section_url)}"
                )
            context["change_fields_url"] = change_fields_url

        # Session keys for storing breadcrumb state
        breadcrumbs_session_key = (
            f"detail_view_breadcrumbs_{self.model._meta.model_name}_{current_id}"
        )
        referer_session_key = (
            f"detail_referer_{self.model._meta.model_name}_{current_id}"
        )

        hx_current_url = self.request.headers.get("HX-Current-URL")
        http_referer = self.request.META.get("HTTP_REFERER")

        is_reload = False
        if hx_current_url:
            current_path = urlparse(hx_current_url).path
            is_reload = current_path == self.request.path

        if is_reload:
            stored_breadcrumbs = self.request.session.get(breadcrumbs_session_key)
            if stored_breadcrumbs:

                breadcrumbs_for_context = (
                    stored_breadcrumbs[:-1] if stored_breadcrumbs else []
                )
                breadcrumbs_for_context.append((current_obj, None))
                context["breadcrumbs"] = breadcrumbs_for_context
                context["actions"] = detail_actions
                context["model_name"] = self.model._meta.model_name
                effective_pf = self._get_effective_pipeline_field()
                if effective_pf:
                    context["pipeline_field"] = effective_pf
                    context["pipeline_field_verbose_name"] = self.model._meta.get_field(
                        effective_pf
                    ).verbose_name
                return context

        breadcrumbs = []
        stored_referer = self.request.session.get(referer_session_key)

        if hx_current_url and not is_reload:
            referer = hx_current_url
            referer_path = urlparse(referer).path
            if referer_path != self.request.path:
                self.request.session[referer_session_key] = referer
        elif stored_referer:
            referer = stored_referer
        else:
            referer = http_referer
            if referer:
                referer_path = urlparse(referer).path
                if referer_path != self.request.path:
                    self.request.session[referer_session_key] = referer

        dynamic_breadcrumbs = []
        if referer:
            referer_path = urlparse(referer).path
            if referer_path != self.request.path:
                try:
                    resolved = resolve(referer_path)

                    referer_view = (
                        resolved.func.view_class
                        if hasattr(resolved.func, "view_class")
                        else None
                    )
                    is_detail_view = referer_view and issubclass(
                        referer_view, HorillaDetailView
                    )

                    if is_detail_view:
                        session_breadcrumbs = self.request.session.get(
                            "detail_view_breadcrumbs", []
                        )
                        breadcrumbs.extend(session_breadcrumbs)
                    else:
                        label = (
                            resolved.url_name.replace("_", " ")
                            .replace("-", " ")
                            .title()
                            if resolved.url_name
                            else "Back"
                        )
                        for suffix in [
                            " View",
                            " Detail",
                            " List",
                            " Create",
                            " Update",
                            " Delete",
                        ]:
                            if label.endswith(suffix):
                                label = label[: -len(suffix)]
                                break
                        breadcrumbs.append((label, referer))
                except Exception:
                    breadcrumbs.append(("Back", referer))

            dynamic_breadcrumbs = breadcrumbs.copy()

            referrer_app = self.request.GET.get("referrer_app")
            referrer_model = self.request.GET.get("referrer_model")
            referrer_id = self.request.GET.get("referrer_id")
            referrer_label = self.request.GET.get("referrer_label")
            referrer_url = self.request.GET.get("referrer_url")

            if referrer_app and referrer_model and referrer_id:
                if not (
                    referrer_model == self.model._meta.model_name
                    and str(referrer_id) == str(current_id)
                ):
                    try:
                        model_class = apps.get_model(
                            app_label=referrer_app, model_name=referrer_model
                        )
                        obj = model_class.objects.get(pk=referrer_id)
                        obj_title = (
                            str(obj)
                            if hasattr(obj, "__str__")
                            else referrer_label or f"{referrer_model} {referrer_id}"
                        )
                        if referrer_url:
                            try:
                                url = reverse(
                                    f"{referrer_app}:{referrer_url}",
                                    kwargs={"pk": referrer_id},
                                )

                                parsed_url = urlparse(url)
                                query_dict = parse_qs(parsed_url.query)

                                section_for_breadcrumb = None
                                if referrer_app and referrer_model:
                                    try:
                                        model_class = apps.get_model(
                                            app_label=referrer_app,
                                            model_name=referrer_model,
                                        )
                                        section_info = get_section_info_for_model(
                                            model_class
                                        )
                                        section_for_breadcrumb = section_info.get(
                                            "section"
                                        )
                                    except Exception:
                                        section_for_breadcrumb = None

                                if not section_for_breadcrumb:
                                    section_for_breadcrumb = self.request.GET.get(
                                        "section"
                                    )

                                if section_for_breadcrumb:
                                    query_dict["section"] = [section_for_breadcrumb]

                                new_query = urlencode(query_dict, doseq=True)
                                url = urlunparse(parsed_url._replace(query=new_query))

                            except Exception:
                                url = None
                        dynamic_breadcrumbs.append((obj_title, url))
                    except (LookupError, model_class.DoesNotExist, ValueError):
                        if referrer_label and referrer_url:
                            dynamic_breadcrumbs.append((referrer_label, referrer_url))

        dynamic_breadcrumbs.append((current_obj, None))

        session_url_value = self.request.GET.get("session_url")
        if session_url_value:
            updated_breadcrumbs = []
            for label, url in dynamic_breadcrumbs:
                if url:
                    try:
                        parsed_url = urlparse(url)
                        query_dict = parse_qs(parsed_url.query)
                        query_dict["session_url"] = [session_url_value]
                        new_query = urlencode(query_dict, doseq=True)
                        url = urlunparse(parsed_url._replace(query=new_query))
                    except Exception:
                        pass  # Keep original URL if parsing fails
                updated_breadcrumbs.append((label, url))
            dynamic_breadcrumbs = updated_breadcrumbs

        self.request.session["detail_view_breadcrumbs"] = breadcrumbs

        serializable_breadcrumbs = []
        for label, url in dynamic_breadcrumbs:
            if hasattr(label, "_meta"):  # It's a model instance
                label = str(label)
            serializable_breadcrumbs.append((label, url))

        self.request.session[breadcrumbs_session_key] = serializable_breadcrumbs

        context["breadcrumbs"] = dynamic_breadcrumbs
        context["actions"] = detail_actions
        context["model_name"] = self.model._meta.model_name
        effective_pf = self._get_effective_pipeline_field()
        if effective_pf:
            context["pipeline_field"] = effective_pf
            context["pipeline_field_verbose_name"] = self.model._meta.get_field(
                effective_pf
            ).verbose_name
        return context

    def post(self, request, *args, **kwargs):
        """
        Handle POST requests for updating the pipeline field.
        """
        if request.POST.get("pipeline_update"):
            model_name = request.POST.get("model_name")
            app_label = request.POST.get("app_label")
            pipeline_field = request.POST.get("pipeline_field")

            try:
                model = apps.get_model(app_label, model_name)
            except Exception as e:
                messages.error(self.request, e)
                return HttpResponse("<script>$('#reloadButton').click();</script>")

            view_class = self._view_registry.get(model, self.__class__)

            if view_class != self.__class__:
                view_instance = view_class()
                view_instance.request = self.request
                view_instance.args = self.args
                view_instance.kwargs = self.kwargs
                view_instance.model = model
                view_instance.pipeline_field = pipeline_field
                return view_instance.update_pipeline(request, *args, **kwargs)

            self.model = model
            self.pipeline_field = pipeline_field
            return self.update_pipeline(request, *args, **kwargs)

        return HttpResponse(status=400)

    def update_pipeline(self, request, *args, **kwargs):
        """
        Handle HTMX POST request to update the pipeline field value.
        Re-render the Kanban choices template with updated data.
        """
        self.object = self.get_object()

        pipeline_value = request.POST.get("pipeline_value")
        if not pipeline_value:
            return HttpResponse(status=400)

        try:
            # Permission check
            user = request.user
            model_name = self.model._meta.model_name
            app_label = self.model._meta.app_label

            # Check if user is the owner
            is_owner = False
            owner_fields = getattr(self.model, "OWNER_FIELDS", [])

            for owner_field in owner_fields:
                try:
                    field_value = getattr(self.object, owner_field, None)
                    if field_value:
                        # Handle ManyToMany fields
                        if hasattr(field_value, "all"):
                            if user in field_value.all():
                                is_owner = True
                                break
                        # Handle ForeignKey fields
                        elif field_value == user:
                            is_owner = True
                            break
                except Exception:
                    continue

            # Check permissions
            has_permission = False

            if user.is_superuser:
                has_permission = True
            elif is_owner:
                # Check if user has change_own permission
                change_own_perm = f"{app_label}.change_own_{model_name}"
                if user.has_perm(change_own_perm):
                    has_permission = True

            # Check regular change permission if not owner or doesn't have change_own
            if not has_permission:
                change_perm = f"{app_label}.change_{model_name}"
                if user.has_perm(change_perm):
                    has_permission = True

            if not has_permission:
                messages.error(
                    self.request, _("You don't have permission to update this record.")
                )
                return HttpResponse("<script>$('#reloadButton').click();</script>")

            # Proceed with pipeline update
            field = self.model._meta.get_field(self.pipeline_field)
            if hasattr(field, "choices") and field.choices:
                # Validate for choice fields
                if pipeline_value not in [choice[0] for choice in field.choices]:
                    raise ValidationError("Invalid choice")
                setattr(self.object, self.pipeline_field, pipeline_value)
            elif isinstance(field, ForeignKey):
                # Validate for ForeignKey fields
                related_model = field.related_model
                try:
                    related_obj = related_model.objects.get(pk=pipeline_value)
                    setattr(self.object, self.pipeline_field, related_obj)
                except Exception as e:
                    logger.error(e)
            else:
                return HttpResponse(status=400)

            self.object.save()
            messages.success(
                self.request,
                _(f"{self.model._meta.verbose_name} Stage Updated Successfully"),
            )
            if request.POST.get("layout") == "split":
                context = self.get_context_data(object=self.object)
                context["body"] = self.get_detail_section_body()
                # Use detail view's url name and namespace for prev/next links (request.path
                # is update_pipeline here, which would break {% url app_label:url_name %}).
                if hasattr(self.object, "get_detail_url"):
                    try:
                        detail_path = str(self.object.get_detail_url())
                        if detail_path:
                            resolved = resolve(detail_path)
                            context["url_name"] = resolved.url_name
                            ns = getattr(resolved, "namespace", None) or getattr(
                                resolved, "app_name", None
                            )
                            if ns:
                                context["app_label"] = ns
                    except Exception:
                        pass
                html = render_to_string(
                    "detail_view_split_fragment.html",
                    context,
                    request=self.request,
                )
                return HttpResponse(html)
            context = self.get_context_data(object=self.object)
            context["pipeline_update"] = True
            kanban_html = render_to_string(
                "partials/pipeline_choices.html", context, request=self.request
            )
            return HttpResponse(kanban_html)
        except Exception as e:
            messages.error(self.request, e)
            return HttpResponse("<script>$('#reloadButton').click();</script>")


class HorillaModalDetailView(DetailView):
    """
    HorillDetailedView
    """

    title = "Detailed View"
    template_name = "single_detail_view.html"
    header: dict = {
        "title": "Horilla",
        "subtitle": "Horilla Detailed View",
        "avatar": "",
    }
    body: list = []

    action_method: list = []
    actions: list = []
    cols: dict = {}
    instance = None
    empty_template = None

    ids_key: str = "instance_ids"

    def get_queryset(self):
        """
        Filter queryset based on instance_ids from session.
        """
        queryset = super().get_queryset()
        instance_ids = self.request.session.get(self.ordered_ids_key, [])
        if instance_ids:
            queryset = queryset.filter(pk__in=instance_ids)
        return queryset

    def get_object(self, queryset=None):
        """Resolve the current object from queryset and store on self.instance."""
        if queryset is None:
            queryset = self.get_queryset()
        try:
            self.instance = super().get_object(queryset)
        except Exception as e:
            logger.error("Error getting object: %s", e)
        return self.instance

    def get(self, request, *args, **kwargs):
        """Initialize session ordered_ids if needed; render empty template or error when no instance."""
        if not self.request.GET.get(self.ids_key) and not self.request.session.get(
            self.ordered_ids_key
        ):
            self.request.session[self.ordered_ids_key] = []
        response = super().get(request, *args, **kwargs)
        if not self.instance and self.empty_template:
            return render(request, self.empty_template, context=self.get_context_data())
        if not self.instance:
            messages.error(request, "The requested record does not exist.")
            return HttpResponse("<script>$('#reloadButton').click();</script>")
        return response

    def __init__(self, **kwargs: Any) -> None:
        """Set ordered_ids_key from model name and attach request from thread local."""
        super().__init__(**kwargs)
        self.ordered_ids_key = f"ordered_ids_{self.model.__name__.lower()}"
        request = getattr(_thread_local, "request", None)
        self.request = request
        # update_initial_cache(request, CACHE, HorillaDetailedView)

    def get_context_data(self, **kwargs: Any):
        """Add ordered instance_ids and navigation data for prev/next to context."""
        context = super().get_context_data(**kwargs)
        obj = context.get("object")

        if not obj:
            return context

        pk = obj.pk
        instance_ids = self.request.session.get(self.ordered_ids_key, [])
        url_info = resolve(self.request.path)
        url_name = url_info.url_name
        key = next(iter(url_info.kwargs), "pk")

        context["instance"] = obj
        context["title"] = self.title
        context["header"] = self.header
        context["body"] = self.body
        context["actions"] = self.actions
        context["action_method"] = self.action_method
        context["cols"] = self.cols

        if instance_ids:
            prev_id, next_id = closest_numbers(instance_ids, pk)

            full_url_name = (
                f"{url_info.namespaces[0]}:{url_name}"
                if url_info.namespaces
                else url_name
            )
            context.update(
                {
                    "instance_ids": str(instance_ids),
                    "ids_key": self.ids_key,
                    "next_url": reverse_lazy(full_url_name, kwargs={key: next_id}),
                    "previous_url": reverse_lazy(full_url_name, kwargs={key: prev_id}),
                }
            )

            # Filter out instance_ids key from GET params
            get_params = self.request.GET.copy()
            get_params.pop(self.ids_key, None)
            context["extra_query"] = get_params.urlencode()
        else:
            context["extra_query"] = ""

        return context
