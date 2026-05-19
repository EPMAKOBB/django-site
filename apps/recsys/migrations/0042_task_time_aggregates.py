from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recsys", "0041_trainingsession_selected_task_type_ids"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="time_spent_avg_seconds",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="time_spent_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="task",
            name="time_spent_sum_seconds",
            field=models.FloatField(default=0.0),
        ),
    ]
