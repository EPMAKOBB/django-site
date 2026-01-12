from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("recsys", "0025_variantpage"),
    ]

    operations = [
        migrations.AddField(
            model_name="variantattempt",
            name="last_seen_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Last heartbeat time for the attempt.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="variantattempt",
            name="active_client_id",
            field=models.UUIDField(
                blank=True,
                help_text="Client id of the active attempt tab.",
                null=True,
            ),
        ),
    ]
