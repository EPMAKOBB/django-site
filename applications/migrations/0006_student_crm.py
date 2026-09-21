import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


def normalize_processed_status(apps, schema_editor):
    Application = apps.get_model("applications", "Application")
    Application.objects.filter(status="processed").update(status="contacted")


def restore_processed_status(apps, schema_editor):
    Application = apps.get_model("applications", "Application")
    Application.objects.filter(status="contacted").update(status="processed")


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("applications", "0005_fix_m2m_subject_fk"),
        ("students", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="application",
            name="status",
            field=models.CharField(
                choices=[
                    ("new", "New"),
                    ("contacted", "Contacted"),
                    ("qualified", "Qualified"),
                    ("trial_scheduled", "Trial scheduled"),
                    ("trial_completed", "Trial completed"),
                    ("converted", "Converted"),
                    ("lost", "Lost"),
                    ("archived", "Archived"),
                    ("processed", "Processed (legacy)"),
                ],
                default="new",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="closed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="application",
            name="lost_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="application",
            name="manager_notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="application",
            name="next_action_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="application",
            name="assigned_to",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_applications", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="application",
            name="contact_person",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="applications", to="students.contactperson"),
        ),
        migrations.CreateModel(
            name="ApplicationStudent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_primary", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("application", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="student_links", to="applications.application")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="application_student_links_created", to=settings.AUTH_USER_MODEL)),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="application_links", to="students.studentrecord")),
            ],
        ),
        migrations.AddConstraint(
            model_name="applicationstudent",
            constraint=models.UniqueConstraint(fields=("application", "student"), name="application_student_unique"),
        ),
        migrations.AddConstraint(
            model_name="applicationstudent",
            constraint=models.UniqueConstraint(condition=Q(("is_primary", True)), fields=("application",), name="application_one_primary_student"),
        ),
        migrations.RunPython(normalize_processed_status, restore_processed_status),
    ]
