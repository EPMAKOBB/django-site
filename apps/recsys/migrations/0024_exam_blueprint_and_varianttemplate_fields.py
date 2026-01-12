from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("recsys", "0023_examversion_slug_status"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExamBlueprint",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(blank=True, max_length=255)),
                ("description", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("time_limit", models.DurationField(blank=True, null=True)),
                ("max_attempts", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "exam_version",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blueprint",
                        to="recsys.examversion",
                    ),
                ),
                (
                    "subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="exam_blueprints",
                        to="subjects.subject",
                    ),
                ),
            ],
            options={
                "ordering": ["exam_version"],
            },
        ),
        migrations.CreateModel(
            name="ExamBlueprintItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("count", models.PositiveIntegerField(default=1)),
                ("order", models.PositiveIntegerField(default=1)),
                ("section", models.CharField(blank=True, max_length=64)),
                ("score_override", models.PositiveSmallIntegerField(blank=True, null=True)),
                (
                    "blueprint",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="recsys.examblueprint",
                    ),
                ),
                (
                    "task_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blueprint_items",
                        to="recsys.tasktype",
                    ),
                ),
            ],
            options={
                "ordering": ["order", "id"],
            },
        ),
        migrations.AddField(
            model_name="varianttemplate",
            name="display_order",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="varianttemplate",
            name="exam_version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="variant_templates",
                to="recsys.examversion",
            ),
        ),
        migrations.AddField(
            model_name="varianttemplate",
            name="is_public",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="varianttemplate",
            name="kind",
            field=models.CharField(
                choices=[
                    ("personal", "Personal"),
                    ("demo", "Demo"),
                    ("official", "Official/EGKR"),
                    ("book", "Book collection"),
                    ("teacher", "Teacher draft"),
                    ("custom", "Custom"),
                ],
                default="custom",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="varianttemplate",
            name="slug",
            field=models.SlugField(blank=True, max_length=128, null=True),
        ),
        migrations.AlterModelOptions(
            name="varianttemplate",
            options={"ordering": ["display_order", "name"]},
        ),
        migrations.AddIndex(
            model_name="examblueprint",
            index=models.Index(fields=["exam_version", "is_active"], name="recsys_examb_exam_vers_0a3a9e_idx"),
        ),
        migrations.AddConstraint(
            model_name="examblueprintitem",
            constraint=models.UniqueConstraint(
                fields=("blueprint", "task_type"), name="blueprint_task_type_unique"
            ),
        ),
        migrations.AddConstraint(
            model_name="examblueprintitem",
            constraint=models.UniqueConstraint(fields=("blueprint", "order"), name="blueprint_order_unique"),
        ),
        migrations.AddIndex(
            model_name="examblueprintitem",
            index=models.Index(fields=["blueprint", "order"], name="recsys_examb_bluepri_3c6497_idx"),
        ),
        migrations.AddIndex(
            model_name="varianttemplate",
            index=models.Index(
                fields=["exam_version", "is_public", "display_order"], name="recsys_varia_exam_ve_1b4795_idx"
            ),
        ),
    ]
