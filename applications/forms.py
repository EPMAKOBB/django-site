from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Application
from subjects.models import Subject


class ApplicationForm(forms.ModelForm):
    grade = forms.TypedChoiceField(
        coerce=int,
        choices=[(9, "9"), (10, "10"), (11, "11")],
        label="",
        required=False,
        empty_value=None,
    )
    subject1 = forms.ModelChoiceField(
        queryset=Subject.objects.all(),
        label="",
        required=False,
    )
    subject2 = forms.ModelChoiceField(
        queryset=Subject.objects.all(),
        required=False,
        label="",
    )
    source_offer = forms.CharField(required=False, widget=forms.HiddenInput())
    lesson_type = forms.ChoiceField(
        choices=[
            ("group", "групповой"),
            ("individual", "индивидуальный"),
        ],
        label="",
        required=False,
    )


    class Meta:
        model = Application
        fields = [
            "grade",
            "subject1",
            "subject2",
            "lesson_type",
            "source_offer",
            "contact_info",
            "contact_name",
        ]
        labels = {
            "contact_info": "",
            "contact_name": "",
        }
        widgets = {
            "contact_info": forms.Textarea(
                attrs={"placeholder": _("Ваши контакты и комментарий")}
            ),
            "contact_name": forms.TextInput(
                attrs={"placeholder": _("Ваше имя")}
            ),
        }

    def save(self, commit: bool = True) -> Application:  # type: ignore[override]
        application = super().save(commit=False)
        application.source_offer = self.cleaned_data.get("source_offer")
        lesson_type = self.cleaned_data.get("lesson_type") or "pass"
        application.lesson_type = lesson_type
        if commit:
            application.save()
            subjects = []
            subject1 = self.cleaned_data.get("subject1")
            if subject1:
                subjects.append(subject1)
            subject2 = self.cleaned_data.get("subject2")
            if subject2:
                subjects.append(subject2)
            application.subjects.set(subjects)
        return application

