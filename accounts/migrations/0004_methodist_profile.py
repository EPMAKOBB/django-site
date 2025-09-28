from django.db import migrations, models
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_teacher_student_and_classes"),
    ]

    operations = [
        migrations.CreateModel(
            name="MethodistProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bio", models.TextField(blank=True)),
                (
                    "user",
                    models.OneToOneField(on_delete=models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
                ),
            ],
        )
    ]

