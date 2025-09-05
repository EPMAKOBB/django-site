from django import forms

from .models import Application


class ApplicationForm(forms.ModelForm):
    class Meta:
        model = Application
        fields = [
            "contact_name",
            "student_name",
            "grade",
            "subjects",
            "contact_info",
            "lesson_type",
            "source_offer",
        ]
