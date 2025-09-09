from typing import Any, Dict
from django.urls import reverse_lazy
from django.views.generic import FormView

from .forms import ApplicationForm
from subjects.models import Subject
from .utils import get_application_price


class ApplicationCreateView(FormView):
    template_name = "applications/application_form.html"
    form_class = ApplicationForm
    success_url = reverse_lazy("applications:apply")

    def get_initial(self) -> Dict[str, Any]:  # type: ignore[override]
        initial = super().get_initial()
        source_offer = self.request.GET.get("source_offer")
        if source_offer:
            initial["source_offer"] = source_offer
            slug, *rest = source_offer.split("-")
            try:
                subject = Subject.objects.get(slug=slug)
                initial["subject1"] = subject.pk
            except Subject.DoesNotExist:
                pass
            if rest and rest[0].isdigit():
                initial["grade"] = int(rest[0])
        return initial

    def form_valid(self, form: ApplicationForm) -> Any:  # type: ignore[override]
        form.save()
        return super().form_valid(form)

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:  # type: ignore[override]
        context = super().get_context_data(**kwargs)
        form: ApplicationForm = context.get("form")
        subjects_count = 0
        if form:
            data = form.data if form.is_bound else form.initial
            if data.get("subject1"):
                subjects_count += 1
            if data.get("subject2"):
                subjects_count += 1
        context["application_price"] = get_application_price(
            subjects_count,
        )
        return context
