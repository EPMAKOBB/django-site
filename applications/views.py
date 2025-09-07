from typing import Any, Dict
from datetime import date

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
        lesson_type = "group"
        subjects_count = 0
        if form:
            data = form.data if form.is_bound else form.initial
            subjects_count = sum(
                1 for field in ("subject1", "subject2") if data.get(field)
            )
            lesson_type = data.get("lesson_type") or lesson_type
        context["application_price"] = get_application_price(
            lesson_type,
            subjects_count,
            promo_until=date(date.today().year, 9, 30),
        )
        return context
