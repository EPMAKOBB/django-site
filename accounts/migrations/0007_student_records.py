from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_student_records(apps, schema_editor):
    TeacherStudentLink = apps.get_model("accounts", "TeacherStudentLink")
    StudentRecord = apps.get_model("students", "StudentRecord")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))

    for link in TeacherStudentLink.objects.exclude(student_id=None).iterator():
        student = User.objects.get(pk=link.student_id)
        full_name = " ".join(part for part in (student.first_name, student.last_name) if part).strip()
        record, _ = StudentRecord.objects.get_or_create(
            user_id=student.pk,
            defaults={
                "full_name": full_name or student.username,
                "status": "active",
                "created_by_id": link.teacher_id,
            },
        )
        TeacherStudentLink.objects.filter(pk=link.pk).update(student_record_id=record.pk)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_userpreferences"),
        ("students", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="teacherstudentlink",
            name="student_record",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="teacher_links", to="students.studentrecord"),
        ),
        migrations.AlterField(
            model_name="teacherstudentlink",
            name="student",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="teacher_links", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(model_name="teacherstudentlink", name="currency", field=models.CharField(default="RUB", max_length=3)),
        migrations.AddField(model_name="teacherstudentlink", name="default_duration_minutes", field=models.PositiveSmallIntegerField(default=60, validators=[django.core.validators.MinValueValidator(1)])),
        migrations.AddField(model_name="teacherstudentlink", name="default_price_amount", field=models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=10, validators=[django.core.validators.MinValueValidator(Decimal("0.00"))])),
        migrations.AddField(model_name="teacherstudentlink", name="ended_at", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="teacherstudentlink", name="notes", field=models.TextField(blank=True)),
        migrations.AddField(model_name="teacherstudentlink", name="started_at", field=models.DateField(blank=True, null=True)),
        migrations.RunPython(backfill_student_records, migrations.RunPython.noop),
    ]
