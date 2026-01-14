from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recsys", "0032_detach_answerschema_exam_schema"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("review", "Review"),
                    ("changes_requested", "Changes requested"),
                    ("approved", "Approved"),
                    ("scheduled", "Scheduled"),
                    ("published", "Published"),
                    ("archived", "Archived"),
                    ("rejected", "Rejected"),
                ],
                default="draft",
                max_length=32,
            ),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(fields=["status"], name="recsys_task_status_idx"),
        ),
    ]
