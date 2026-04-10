from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recsys", "0040_trainingsession_trainingsessionstep_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="trainingsession",
            name="selected_task_type_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
