from django.views.generic import TemplateView

from applications.forms import ApplicationForm
from applications.utils import get_application_price


class HomeView(TemplateView):
    """Render the main landing page."""
    template_name = "home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = ApplicationForm()
        context["application_price"] = get_application_price(0)
        return context

