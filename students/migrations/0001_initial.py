import uuid

import django.db.models.deletion
import students.models
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ContactPerson",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("full_name", models.CharField(max_length=255)),
                ("phone", models.CharField(blank=True, db_index=True, max_length=32)),
                ("email", models.EmailField(blank=True, db_index=True, max_length=254)),
                ("telegram_username", models.CharField(blank=True, max_length=64)),
                ("timezone", models.CharField(blank=True, max_length=64, validators=[students.models.validate_timezone_name])),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="student_contact_persons", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("full_name", "id")},
        ),
        migrations.CreateModel(
            name="StudentRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("full_name", models.CharField(max_length=255)),
                ("status", models.CharField(choices=[("lead", "Потенциальный"), ("contacted", "Связались"), ("trial", "Пробный период"), ("active", "Занимается"), ("paused", "Пауза"), ("finished", "Закончил"), ("lost", "Отказался"), ("archived", "Архив")], default="lead", max_length=16)),
                ("grade", models.PositiveSmallIntegerField(blank=True, null=True, validators=[MinValueValidator(1), MaxValueValidator(11)])),
                ("city", models.CharField(blank=True, max_length=120)),
                ("timezone", models.CharField(default="Europe/Moscow", max_length=64, validators=[students.models.validate_timezone_name])),
                ("notes", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="student_records_created", to=settings.AUTH_USER_MODEL)),
                ("user", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="student_record", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("full_name", "id"),
                "indexes": [
                    models.Index(fields=["status", "full_name"], name="students_status_name_idx"),
                    models.Index(fields=["full_name"], name="students_full_name_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="StudentAccountInvite",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("expires_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="student_account_invites_created", to=settings.AUTH_USER_MODEL)),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="account_invites", to="students.studentrecord")),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [models.Index(fields=["student", "expires_at"], name="students_invite_expiry_idx")],
            },
        ),
        migrations.CreateModel(
            name="StudentContact",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("relationship", models.CharField(choices=[("self", "Сам ученик"), ("mother", "Мать"), ("father", "Отец"), ("guardian", "Опекун"), ("relative", "Родственник"), ("other", "Другое")], max_length=16)),
                ("is_primary", models.BooleanField(default=False)),
                ("is_payer", models.BooleanField(default=False)),
                ("receives_schedule", models.BooleanField(default=True)),
                ("receives_reschedules", models.BooleanField(default=True)),
                ("receives_payment_notifications", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("contact", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="student_links", to="students.contactperson")),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="contact_links", to="students.studentrecord")),
            ],
        ),
        migrations.CreateModel(
            name="StudentStatusEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("from_status", models.CharField(blank=True, max_length=16)),
                ("to_status", models.CharField(choices=[("lead", "Потенциальный"), ("contacted", "Связались"), ("trial", "Пробный период"), ("active", "Занимается"), ("paused", "Пауза"), ("finished", "Закончил"), ("lost", "Отказался"), ("archived", "Архив")], max_length=16)),
                ("reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="student_status_changes", to=settings.AUTH_USER_MODEL)),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="status_events", to="students.studentrecord")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddConstraint(
            model_name="studentcontact",
            constraint=models.UniqueConstraint(fields=("student", "contact", "relationship"), name="student_contact_relationship_unique"),
        ),
        migrations.AddConstraint(
            model_name="studentcontact",
            constraint=models.UniqueConstraint(condition=Q(("is_active", True), ("is_primary", True)), fields=("student",), name="student_one_active_primary_contact"),
        ),
    ]
