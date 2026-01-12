from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recsys", "0028_alter_examversion_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="examversion",
            name="start_info",
            field=models.TextField(blank=True, help_text="Reference info shown at the start of the exam."),
        ),
    ]
