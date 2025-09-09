from django.views.generic import TemplateView

from applications.forms import ApplicationForm
from applications.utils import get_application_price


class HomeView(TemplateView):
    """Render the main landing page."""
    template_name = "home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = ApplicationForm(self.request.GET or None)
        context["form"] = form

        subjects_count = 0
        data = form.data if form.is_bound else form.initial
        if data.get("subject1"):
            subjects_count += 1
        if data.get("subject2"):
            subjects_count += 1

        context["subjects_count"] = subjects_count
        context["application_price"] = get_application_price(subjects_count)
        return context

