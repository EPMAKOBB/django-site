from django.views.generic import TemplateView

from applications.forms import ApplicationForm
from applications.utils import date, get_application_price


class HomeView(TemplateView):
    """Render the main landing page."""
    template_name = "home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form"] = ApplicationForm()
        context["application_price"] = get_application_price(
            "group", 1, promo_until=date(date.today().year, 9, 30)
        )
        return context

