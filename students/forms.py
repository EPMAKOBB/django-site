from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import TeacherStudentLink
from subjects.models import Subject

from .models import ContactPerson, StudentContact, StudentRecord, StudentStatusEvent


class LessonDefaultsForm(forms.Form):
    default_duration_minutes = forms.IntegerField(
        label="Длительность урока, минут", min_value=1, max_value=32767, initial=60,
    )
    default_price_amount = forms.DecimalField(
        label="Стоимость урока", min_value=Decimal("0.00"), max_digits=10,
        decimal_places=2, initial=Decimal("2000.00"),
    )
    currency = forms.CharField(label="Валюта", min_length=3, max_length=3, initial="RUB")

    def clean_currency(self):
        currency = self.cleaned_data["currency"].upper()
        if not currency.isascii() or not currency.isalpha():
            raise forms.ValidationError("Укажите трёхбуквенный код валюты, например RUB.")
        return currency


class StudentLessonDefaultsForm(LessonDefaultsForm):
    def __init__(self, *args, instance, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance
        self.initial.update({name: getattr(instance, name) for name in self.fields})

    def save(self):
        for name in self.fields:
            setattr(self.instance, name, self.cleaned_data[name])
        self.instance.save(update_fields=list(self.fields))
        return self.instance


class StudentSubjectForm(LessonDefaultsForm):
    subject = forms.ModelChoiceField(label="Предмет", queryset=Subject.objects.none())
    field_order = ["subject", "default_duration_minutes", "default_price_amount", "currency"]

    def __init__(self, *args, teacher, student, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher, self.student = teacher, student
        existing = TeacherStudentLink.objects.filter(teacher=teacher, student_record=student)
        self.fields["subject"].queryset = Subject.objects.exclude(
            pk__in=existing.values("subject_id")
        ).order_by("name")

    @transaction.atomic
    def save(self):
        # Serialize additions to this student's card, including duplicate submits.
        StudentRecord.objects.select_for_update().get(pk=self.student.pk)
        if TeacherStudentLink.objects.filter(
            teacher=self.teacher, student_record=self.student, subject=self.cleaned_data["subject"],
        ).exists():
            raise ValidationError("Этот предмет уже добавлен ученику.")
        return TeacherStudentLink.objects.create(
            teacher=self.teacher, student_record=self.student,
            subject=self.cleaned_data["subject"], status=TeacherStudentLink.Status.ACTIVE,
            default_duration_minutes=self.cleaned_data["default_duration_minutes"],
            default_price_amount=self.cleaned_data["default_price_amount"],
            currency=self.cleaned_data["currency"], started_at=timezone.localdate(),
        )


class UnregisteredStudentForm(forms.Form):
    full_name = forms.CharField(label="Имя ученика", max_length=255)
    status = forms.ChoiceField(
        label="Статус",
        choices=StudentRecord.Status.choices,
        initial=StudentRecord.Status.ACTIVE,
    )
    grade = forms.IntegerField(label="Класс", min_value=1, max_value=11, required=False)
    subject = forms.ModelChoiceField(
        label="Предмет",
        queryset=Subject.objects.none(),
    )
    timezone = forms.CharField(
        label="Часовой пояс",
        max_length=64,
        initial="Europe/Moscow",
    )
    default_duration_minutes = forms.IntegerField(
        label="Обычная длительность, минут",
        min_value=1,
        initial=60,
    )
    default_price_amount = forms.DecimalField(
        label="Стоимость урока",
        min_value=Decimal("0.00"),
        max_digits=10,
        decimal_places=2,
        initial=Decimal("2000.00"),
    )
    contact_name = forms.CharField(label="Контактное лицо", max_length=255, required=False)
    contact_phone = forms.CharField(label="Телефон", max_length=32, required=False)
    contact_email = forms.EmailField(label="Email", required=False)
    relationship = forms.ChoiceField(
        label="Кем приходится",
        choices=StudentContact.Relationship.choices,
        initial=StudentContact.Relationship.SELF,
    )
    notes = forms.CharField(label="Заметки", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, teacher, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher = teacher
        self.fields["subject"].queryset = Subject.objects.order_by("name")
        preferences = getattr(teacher, "preferences", None)
        if preferences:
            self.initial["timezone"] = preferences.timezone

    def clean(self):
        cleaned = super().clean()
        if (cleaned.get("contact_phone") or cleaned.get("contact_email")) and not cleaned.get("contact_name"):
            self.add_error("contact_name", "Укажите имя контактного лица.")
        return cleaned

    @transaction.atomic
    def save(self):
        student = StudentRecord.objects.create(
            full_name=self.cleaned_data["full_name"],
            status=self.cleaned_data["status"],
            grade=self.cleaned_data.get("grade"),
            timezone=self.cleaned_data["timezone"],
            notes=self.cleaned_data.get("notes", ""),
            created_by=self.teacher,
            started_at=(
                timezone.now()
                if self.cleaned_data["status"] == StudentRecord.Status.ACTIVE
                else None
            ),
        )
        StudentStatusEvent.objects.create(
            student=student,
            to_status=student.status,
            changed_by=self.teacher,
            reason="Карточка создана вручную",
        )
        if self.cleaned_data.get("contact_name"):
            contact = ContactPerson.objects.create(
                full_name=self.cleaned_data["contact_name"],
                phone=self.cleaned_data.get("contact_phone", ""),
                email=self.cleaned_data.get("contact_email", ""),
            )
            StudentContact.objects.create(
                student=student,
                contact=contact,
                relationship=self.cleaned_data["relationship"],
                is_primary=True,
                is_payer=True,
            )
        link = TeacherStudentLink.objects.create(
            teacher=self.teacher,
            student_record=student,
            subject=self.cleaned_data["subject"],
            status=TeacherStudentLink.Status.ACTIVE,
            default_duration_minutes=self.cleaned_data["default_duration_minutes"],
            default_price_amount=self.cleaned_data["default_price_amount"],
            started_at=timezone.localdate(),
        )
        return student, link


class StudentRecordForm(forms.ModelForm):
    contact_name = forms.CharField(label="Основное контактное лицо", max_length=255, required=False)
    contact_phone = forms.CharField(label="Телефон", max_length=32, required=False)
    contact_email = forms.EmailField(label="Email", required=False)

    class Meta:
        model = StudentRecord
        fields = ("full_name", "status", "grade", "city", "timezone", "notes")
        labels = {
            "full_name": "Имя ученика",
            "status": "Статус",
            "grade": "Класс",
            "city": "Город",
            "timezone": "Часовой пояс",
            "notes": "Заметки",
        }
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.primary_link = (
            self.instance.contact_links.filter(is_primary=True, is_active=True)
            .select_related("contact")
            .first()
            if self.instance.pk
            else None
        )
        if self.primary_link:
            self.initial.update(
                {
                    "contact_name": self.primary_link.contact.full_name,
                    "contact_phone": self.primary_link.contact.phone,
                    "contact_email": self.primary_link.contact.email,
                }
            )

    @transaction.atomic
    def save(self, commit=True):
        old_status = StudentRecord.objects.get(pk=self.instance.pk).status
        student = super().save(commit=commit)
        if old_status != student.status:
            StudentStatusEvent.objects.create(
                student=student,
                from_status=old_status,
                to_status=student.status,
                changed_by=self.actor,
            )
        contact_name = self.cleaned_data.get("contact_name", "").strip()
        if self.primary_link and contact_name:
            contact = self.primary_link.contact
            contact.full_name = contact_name
            contact.phone = self.cleaned_data.get("contact_phone", "")
            contact.email = self.cleaned_data.get("contact_email", "")
            contact.save()
        elif contact_name:
            contact = ContactPerson.objects.create(
                full_name=contact_name,
                phone=self.cleaned_data.get("contact_phone", ""),
                email=self.cleaned_data.get("contact_email", ""),
            )
            StudentContact.objects.create(
                student=student,
                contact=contact,
                relationship=StudentContact.Relationship.OTHER,
                is_primary=True,
                is_payer=True,
            )
        return student
