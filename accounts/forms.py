from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm as DjangoPasswordChangeForm,
)
from django.forms import formset_factory
from django.utils.translation import gettext_lazy as _

from apps.recsys.models import ExamVersion, Skill, Task, TaskTag, TaskType
from subjects.models import Subject

from .models import StudentProfile
from courses.models import Course, CourseTheoryCard

User = get_user_model()


class SignupForm(forms.Form):
    contact = forms.CharField(
        label=_("Контактные данные"),
        max_length=255,
        help_text=_(
            "Укажите email или телефон — они понадобятся в случае восстановления аккаунта"
        ),
    )
    username = forms.CharField(label=_("Логин"), max_length=150)
    password = forms.CharField(label=_("Пароль"), widget=forms.PasswordInput)

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError(_("Этот логин уже занят"))
        return username

    def save(self, commit: bool = True):
        user = User(username=self.cleaned_data["username"], email=self.cleaned_data["contact"])
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class LoginForm(AuthenticationForm):
    pass


class UsernameChangeForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("username",)

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("Этот логин уже занят"))
        return username


class UserUpdateForm(forms.ModelForm):
    """Form for updating basic user information."""

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email")
        labels = {
            "username": _("Логин"),
            "first_name": _("Имя"),
            "last_name": _("Фамилия"),
            "email": _("Электронная почта"),
        }
        error_messages = {
            "username": {"required": _("Укажите логин")},
            "first_name": {"required": _("Укажите имя")},
            "last_name": {"required": _("Укажите фамилию")},
            "email": {
                "required": _("Укажите адрес электронной почты"),
                "invalid": _("Введите правильный адрес электронной почты"),
            },
        }

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("Этот логин уже занят"))
        return username


class PasswordChangeForm(DjangoPasswordChangeForm):
    """Password change form with Russian field labels."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].label = _("Старый пароль")
        self.fields["new_password1"].label = _("Новый пароль")
        self.fields["new_password2"].label = _("Подтверждение нового пароля")


class TaskCreateForm(forms.ModelForm):
    """Form for creating a new static task from the teacher dashboard."""

    correct_answer = forms.CharField(
        label=_("Правильный ответ"),
        required=False,
        help_text=_("Введите текст ответа. Он будет сохранён как структура JSON."),
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    preliminary_difficulty = forms.IntegerField(
        label=_("Предварительная сложность"),
        required=False,
        min_value=0,
        max_value=100,
        help_text=_("Число от 0 до 100. Сохраняется как дополнительная метка сложности."),
    )

    class Meta:
        model = Task
        fields = (
            "subject",
            "exam_version",
            "type",
            "title",
            "description",
            "tags",
            "image",
            "difficulty_level",
            "correct_answer",
        )
        labels = {
            'subject': _('Предмет'),
            'exam_version': _('Вариант экзамена'),
            'type': _('Тип задания'),
            'title': _('Заголовок'),
            'description': _('Описание'),
            'tags': _('Теги задачи'),
            'image': _('Изображение задания'),
            'difficulty_level': _('Сложность'),
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["exam_version"].queryset = ExamVersion.objects.select_related("subject").order_by(
            "subject__name", "name"
        )
        self.fields["type"].queryset = (
            TaskType.objects.select_related("subject", "exam_version")
            .order_by("subject__name", "exam_version__name", "display_order", "name")
        )
        self.fields["subject"].queryset = Subject.objects.order_by("name")
        tags_field = self.fields.get("tags")
        if tags_field is not None:
            tags_queryset = TaskTag.objects.select_related("subject").order_by("subject__name", "name")
            instance_subject = getattr(self.instance, "subject", None)
            subject_for_filter = instance_subject
            if subject_for_filter is None:
                bound_subject = self.data.get(self.add_prefix("subject")) if self.is_bound else None
                subject_for_filter = bound_subject or self.initial.get("subject")
            if subject_for_filter:
                try:
                    subject_id = getattr(subject_for_filter, "id", None) or int(subject_for_filter)
                except (ValueError, TypeError):
                    subject_id = None
                if subject_id is not None:
                    tags_queryset = tags_queryset.filter(subject_id=subject_id)
            tags_field.queryset = tags_queryset
            tags_field.widget = forms.CheckboxSelectMultiple()
            tags_field.required = False
        self.fields["difficulty_level"].min_value = 0
        self.fields["difficulty_level"].max_value = 100
        self.fields["difficulty_level"].help_text = _("Число от 0 до 100.")

    def clean(self):
        cleaned_data = super().clean()
        subject = cleaned_data.get("subject")
        exam = cleaned_data.get("exam_version")
        task_type = cleaned_data.get("type")
        description = cleaned_data.get("description")
        image = cleaned_data.get("image")

        if not description and not image:
            raise forms.ValidationError(
                _("Добавьте текст условия или загрузите скриншот."),
            )

        if subject:
            if exam and exam.subject_id != subject.id:
                self.add_error(
                    "exam_version",
                    _("Версия экзамена должна относиться к выбранному предмету."),
                )
            if task_type and task_type.subject_id != subject.id:
                self.add_error(
                    "type",
                    _("Тип задания должен относиться к выбранному предмету."),
                )

        return cleaned_data

    def clean_tags(self):
        tags = self.cleaned_data.get("tags")
        subject = self.cleaned_data.get("subject")
        if subject and tags:
            invalid = [tag for tag in tags if tag.subject_id != subject.id]
            if invalid:
                raise forms.ValidationError(_("Выберите теги, относящиеся к выбранному предмету."))
        return tags

    def clean_correct_answer(self):
        answer_text = self.cleaned_data.get("correct_answer")
        if not answer_text:
            return {}
        return {"text": answer_text.strip()}

    def save(self, commit: bool = True):
        task = super().save(commit=False)
        preliminary = self.cleaned_data.get("preliminary_difficulty")
        payload = dict(task.default_payload or {})
        if preliminary is not None:
            payload["preliminary_difficulty"] = preliminary
        task.default_payload = payload
        if commit:
            task.save()
            self.save_m2m()
        return task


class TaskSkillForm(forms.Form):
    """Form for selecting skills linked to a task."""

    skill = forms.ModelChoiceField(
        label=_("Умение"),
        queryset=Skill.objects.none(),
        required=False,
    )
    weight = forms.DecimalField(
        label=_("Вес умения"),
        required=False,
        min_value=0,
        max_value=10,
        decimal_places=2,
        initial=1,
        help_text=_("Вес влияет на вклад умения в задачу."),
    )

    def set_subject(self, subject: Subject | None) -> None:
        queryset = Skill.objects.select_related("subject").order_by("subject__name", "name")
        if subject:
            queryset = queryset.filter(subject=subject)
        self.fields["skill"].queryset = queryset

    def clean(self):
        cleaned_data = super().clean()
        skill = cleaned_data.get("skill")
        weight = cleaned_data.get("weight")

        if not skill:
            cleaned_data["weight"] = None
            return cleaned_data

        if weight is None:
            cleaned_data["weight"] = self.fields["weight"].initial

        return cleaned_data


TaskSkillFormSet = formset_factory(TaskSkillForm, extra=1, can_delete=True)


def build_task_skill_formset(*, subject: Subject | None, data=None, prefix: str = "skills"):
    """Return a formset configured for the given subject."""

    formset = TaskSkillFormSet(data=data, prefix=prefix)
    for form in formset.forms:
        form.set_subject(subject)
    formset.empty_form.set_subject(subject)
    return formset


# Methodist forms
class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = (
            "slug",
            "title",
            "subtitle",
            "short_description",
            "level",
            "language",
            "is_active",
            "enrollment_open",
        )


class CourseTheoryCardForm(forms.ModelForm):
    class Meta:
        model = CourseTheoryCard
        fields = (
            "course",
            "slug",
            "title",
            "subtitle",
            "content",
            "content_format",
            "estimated_duration_minutes",
            "difficulty_level",
        )
