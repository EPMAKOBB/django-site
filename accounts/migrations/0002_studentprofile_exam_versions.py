from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("recsys", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="studentprofile",
            name="exam_versions",
            field=models.ManyToManyField(
                blank=True,
                help_text="Выбранные версии экзаменов, к которым готовится студент",
                related_name="students_preparing",
                to="recsys.examversion",
            ),
        ),
    ]

