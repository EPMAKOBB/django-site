from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recsys", "0022_rename_recsys_var_variant_081fa0_idx_recsys_vari_variant_cff3a1_idx_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name="examversion",
                    name="slug",
                    field=models.SlugField(
                        max_length=128,
                        null=True,
                        blank=True,
                        db_index=True,
                    ),
                ),
                migrations.AddField(
                    model_name="examversion",
                    name="status",
                    field=models.CharField(
                        choices=[("draft", "Draft"), ("active", "Active")],
                        default="draft",
                        max_length=32,
                        null=True,
                        blank=True,
                        db_index=True,
                    ),
                ),
                migrations.AlterModelOptions(
                    name="examversion",
                    options={
                        "indexes": [
                            models.Index(fields=["subject", "name"], name="recsys_exam_subject_name_idx"),
                            models.Index(fields=["slug"], name="recsys_exam_slug_idx"),
                            models.Index(fields=["status"], name="recsys_exam_status_idx"),
                        ],
                        "ordering": ["name"],
                        "unique_together": {("subject", "name")},
                    },
                ),
            ],
        ),
    ]
