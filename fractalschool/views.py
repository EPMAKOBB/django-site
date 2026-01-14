from django.http import HttpResponse
from django.views.generic import TemplateView

from applications.forms import ApplicationForm
from applications.utils import get_application_price
from apps.recsys.models import ExamVersion


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
        context["active_exams"] = (
            ExamVersion.objects.filter(status=ExamVersion.Status.ACTIVE)
            .select_related("subject")
            .order_by("subject__name", "name")
        )
        return context


def robots_txt(request):
    sitemap_url = f"{request.scheme}://{request.get_host()}/sitemap.xml"
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /accounts/",
        "Disallow: /tasks/",
        "Disallow: /recsys/",
        "Disallow: /parser/",
        "Disallow: /api/",
        "Allow: /",
        f"Sitemap: {sitemap_url}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")
