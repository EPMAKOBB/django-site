from django import forms

from .models import Application


class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = [
            "grade",
            "subjects",
            "contact_info",
            "contact_name",
            "lesson_type",
        ]
