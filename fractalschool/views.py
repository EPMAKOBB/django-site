from django.views.generic import TemplateView


class HomeView(TemplateView):
    """Render the main landing page."""
    template_name = "home.html"

