from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("recsys", "0026_variantattempt_heartbeat_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExamScoreScale",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("max_primary", models.PositiveSmallIntegerField(help_text="Maximum primary score supported by this scale.")),
                (
                    "mapping",
                    models.JSONField(
                        blank=True,
                        default=list,
                        help_text="List where index=primary score and value=secondary score.",
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                (
                    "exam_version",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="score_scale",
                        to="recsys.examversion",
                    ),
                ),
            ],
            options={
                "ordering": ["exam_version"],
            },
        ),
    ]
