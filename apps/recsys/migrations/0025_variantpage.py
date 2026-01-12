from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("recsys", "0024_exam_blueprint_and_varianttemplate_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="VariantPage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("slug", models.SlugField(max_length=128, unique=True)),
                ("title", models.CharField(blank=True, max_length=255)),
                ("description", models.TextField(blank=True)),
                ("is_public", models.BooleanField(default=True)),
                (
                    "template",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="page",
                        to="recsys.varianttemplate",
                    ),
                ),
            ],
            options={
                "ordering": ["slug"],
                "indexes": [models.Index(fields=["slug"], name="recsys_var_sl_a2f963_idx")],
            },
        ),
    ]
