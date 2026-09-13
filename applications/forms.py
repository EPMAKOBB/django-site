from django import forms
from django.utils.translation import gettext_lazy as _

from subjects.models import Subject

from .models import Application


class ApplicationForm(forms.ModelForm):
    grade = forms.TypedChoiceField(
        coerce=int,
        choices=[("", _("Выберите класс"))] + [(value, str(value)) for value in range(1, 12)],
        label=_("Класс"),
        required=False,
        empty_value=None,
        widget=forms.Select(),
    )
    subjects = forms.ModelMultipleChoiceField(
        queryset=Subject.objects.none(),
        label=_("Предметы"),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    source_offer = forms.CharField(required=False, widget=forms.HiddenInput())
    lesson_type = forms.CharField(required=False, initial="pass", widget=forms.HiddenInput())

    class Meta:
        model = Application
        fields = [
            "grade",
            "subjects",
            "lesson_type",
            "source_offer",
            "contact_name",
            "student_name",
            "contact_info",
        ]
        labels = {
            "contact_name": _("Имя контактного лица"),
            "student_name": _("Имя ученика"),
            "contact_info": _("Ваш телефон"),
        }
        widgets = {
            "contact_name": forms.TextInput(
                attrs={
                    "placeholder": _("Ваше имя"),
                    "autocomplete": "name",
                }
            ),
            "contact_info": forms.TextInput(
                attrs={
                    "placeholder": _("Введите телефон"),
                    "inputmode": "tel",
                    "autocomplete": "tel",
                }
            ),
            "student_name": forms.TextInput(
                attrs={"placeholder": _("Имя ученика (если отличается)")}
            ),
    }

    def __init__(self, *args, **kwargs):
        # Keep compatibility with the older landing-page payload while the
        # public forms are gradually switched to the `subjects` checkbox list.
        source_data = args[0] if args else kwargs.get("data")
        if source_data is not None and hasattr(source_data, "copy"):
            data = source_data.copy()
            if not data.getlist("subjects"):
                legacy_subjects = [
                    data.get(field_name)
                    for field_name in ("subject1", "subject2")
                    if data.get(field_name) not in (None, "", "0", "none")
                ]
                if legacy_subjects:
                    data.setlist("subjects", legacy_subjects)
            if args:
                args = (data, *args[1:])
            else:
                kwargs["data"] = data
        super().__init__(*args, **kwargs)
        self.fields["subjects"].queryset = Subject.objects.order_by("name")
        self.fields["grade"].widget.attrs.update(
            {"aria-label": str(self.fields["grade"].label)}
        )

    def save(self, commit: bool = True) -> Application:  # type: ignore[override]
        application = super().save(commit=False)
        application.source_offer = self.cleaned_data.get("source_offer")
        application.lesson_type = self.cleaned_data.get("lesson_type") or "pass"
        if commit:
            application.save()
            application.subjects.set(self.cleaned_data.get("subjects") or [])
        return application
