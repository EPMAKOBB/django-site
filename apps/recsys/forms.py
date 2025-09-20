from __future__ import annotations

from typing import Iterable

from django import forms
from django.core.exceptions import ValidationError

from subjects.models import Subject

from .models import ExamVersion, Skill, Task, TaskSkill, TaskType


class TaskCreateForm(forms.ModelForm):
    skills = forms.ModelMultipleChoiceField(
        queryset=Skill.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-control"}),
        label="Умения",
        help_text="Выберите умения, которые проверяет задача.",
    )

    class Meta:
        model = Task
        fields = [
            "subject",
            "exam_version",
            "type",
            "title",
            "description",
            "statement_image",
            "difficulty",
            "preliminary_difficulty",
            "correct_answer",
        ]
        widgets = {
            "description": forms.Textarea(
                attrs={"rows": 4, "class": "form-control", "placeholder": "Текст условия"}
            ),
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "difficulty": forms.NumberInput(
                attrs={"class": "form-control", "min": 1, "max": 100}
            ),
            "preliminary_difficulty": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.1"}
            ),
            "correct_answer": forms.Textarea(
                attrs={"rows": 2, "class": "form-control", "placeholder": "Правильный ответ"}
            ),
            "subject": forms.Select(attrs={"class": "form-control"}),
            "exam_version": forms.Select(attrs={"class": "form-control"}),
            "type": forms.Select(attrs={"class": "form-control"}),
            "statement_image": forms.ClearableFileInput(
                attrs={"class": "form-control", "accept": "image/*"}
            ),
        }
        labels = {
            "description": "Условие (текст)",
            "statement_image": "Условие (скриншот)",
            "difficulty": "Сложность",
            "preliminary_difficulty": "Предварительная сложность",
            "correct_answer": "Правильный ответ",
            "exam_version": "Экзамен",
            "type": "Тип задания",
            "subject": "Предмет",
            "title": "Заголовок",
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["subject"].queryset = Subject.objects.all().order_by("name")
        self._setup_dependent_fields()

    def _setup_dependent_fields(self) -> None:
        subject = self._get_selected_subject()
        if subject:
            self.fields["exam_version"].queryset = ExamVersion.objects.filter(
                subject=subject
            ).order_by("name")
            self.fields["type"].queryset = TaskType.objects.filter(subject=subject).order_by(
                "name"
            )
            self.fields["skills"].queryset = Skill.objects.filter(subject=subject).order_by(
                "name"
            )
        else:
            self.fields["exam_version"].queryset = ExamVersion.objects.all().order_by("name")
            self.fields["type"].queryset = TaskType.objects.all().order_by("name")
            self.fields["skills"].queryset = Skill.objects.all().select_related("subject").order_by(
                "subject__name",
                "name",
            )

        self.fields["skills"].label_from_instance = (
            lambda skill: f"{skill.subject.name}: {skill.name}"
            if hasattr(skill, "subject") and skill.subject
            else skill.name
        )

        if self.instance.pk:
            self.fields["skills"].initial = self.instance.skills.all()

    def _get_selected_subject(self) -> Subject | None:
        subject_id: str | None
        if self.is_bound:
            subject_id = self.data.get("subject")
        else:
            subject_id = self.initial.get("subject")
        if not subject_id:
            if self.instance and self.instance.subject_id:
                return self.instance.subject
            return None
        try:
            return Subject.objects.get(pk=int(subject_id))
        except (Subject.DoesNotExist, TypeError, ValueError):
            return None

    def clean(self):
        cleaned_data = super().clean()
        description = cleaned_data.get("description")
        statement_image = cleaned_data.get("statement_image")
        if not description and not statement_image:
            raise ValidationError(
                "Необходимо заполнить текст условия или загрузить скриншот."
            )
        return cleaned_data

    def clean_skills(self):
        skills = self.cleaned_data.get("skills")
        subject = self.cleaned_data.get("subject") or self._get_selected_subject()
        if subject and skills:
            invalid = [skill for skill in skills if skill.subject_id != subject.id]
            if invalid:
                raise ValidationError(
                    "Выберите умения, относящиеся к выбранному предмету."
                )
        return skills

    def save(self, commit: bool = True) -> Task:
        task = super().save(commit=commit)
        skills = list(self.cleaned_data.get("skills") or [])
        if commit:
            self._save_skills(task, skills)
        else:
            self._pending_skills = skills
        return task

    def save_m2m(self) -> None:
        super().save_m2m()
        if hasattr(self, "_pending_skills"):
            self._save_skills(self.instance, self._pending_skills)
            delattr(self, "_pending_skills")

    def _save_skills(self, task: Task, skills: Iterable[Skill]) -> None:
        TaskSkill.objects.filter(task=task).delete()
        weight = self.cleaned_data.get("preliminary_difficulty") or 1.0
        for skill in skills:
            TaskSkill.objects.create(task=task, skill=skill, weight=weight)
