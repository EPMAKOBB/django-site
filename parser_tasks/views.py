from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.urls import reverse_lazy
from django.views.generic import FormView

from .forms import ParserRunForm
from .models import ParserRun
from .services import ParserServiceError, run_parser


class ParserControlView(LoginRequiredMixin, UserPassesTestMixin, FormView):
    template_name = "parser_tasks/control.html"
    form_class = ParserRunForm
    success_url = reverse_lazy("parser_tasks:control")

    def test_func(self) -> bool:
        return self.request.user.is_superuser

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied("Доступ разрешен только суперпользователям")
        return super().handle_no_permission()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["runs"] = ParserRun.objects.all()[:10]
        return context

    def form_valid(self, form: ParserRunForm):
        source_url = form.cleaned_data["source_url"]
        try:
            result = run_parser(source_url)
        except ParserServiceError as exc:
            messages.error(self.request, str(exc))
        else:
            messages.success(
                self.request,
                f"Парсинг завершен. Загружено заданий: {result.tasks_count}.",
            )
        return super().form_valid(form)
