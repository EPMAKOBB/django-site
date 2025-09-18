from django import forms
from django.utils.translation import gettext_lazy as _

from apps.recsys.models import ExamVersion
from .models import StudentProfile


class ExamPreferencesForm(forms.ModelForm):
    """Form to manage selected exam versions for the current student."""

    exam_versions = forms.ModelMultipleChoiceField(
        label=_("Ваши экзамены"),
        queryset=ExamVersion.objects.select_related("subject").order_by(
            "subject__name", "name"
        ),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = StudentProfile
        fields = ("exam_versions",)

