from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recsys", "0008_tasktag_task_tags_tasktype_required_tags_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="tasktype",
            name="display_order",
            field=models.PositiveIntegerField(
                default=0,
                help_text=(
                    "Controls ordering of types within the same exam version. "
                    "Lower numbers appear first."
                ),
            ),
        ),
        migrations.AlterModelOptions(
            name="tasktype",
            options={"ordering": ["display_order", "name"]},
        ),
        migrations.RemoveIndex(
            model_name="tasktype",
            name="recsys_task_subject_647945_idx",
        ),
        migrations.AddIndex(
            model_name="tasktype",
            index=models.Index(
                fields=["subject", "exam_version", "display_order", "name"],
                name="recsys_task_subject_d282d1_idx",
            ),
        ),
    ]
