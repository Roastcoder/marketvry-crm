"""Views for displaying version information of Horilla and its modules."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from horilla.utils.version import collect_all_versions


class VersionInfotemplateView(LoginRequiredMixin, TemplateView):
    """
    View to display version information of Horilla and its modules.
    """

    template_name = "version_info/info.html"

    def get_context_data(self, **kwargs):
        """
        Add version information to the context.
        """
        context = super().get_context_data(**kwargs)
        module_versions = collect_all_versions()
        context["core_module"] = module_versions["module_versions"][0]
        context["other_modules"] = module_versions["module_versions"][1:]
        return context
