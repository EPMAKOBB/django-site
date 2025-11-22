from django.db import migrations


def clamp_mastery_values(apps, schema_editor):
    SkillMastery = apps.get_model("recsys", "SkillMastery")
    TypeMastery = apps.get_model("recsys", "TypeMastery")

    SkillMastery.objects.filter(mastery__lt=0).update(mastery=0)
    TypeMastery.objects.filter(mastery__lt=0).update(mastery=0)


class Migration(migrations.Migration):
    dependencies = [
        ("recsys", "0010_taskpregenerateddataset_and_more"),
    ]

    operations = [
        migrations.RunPython(clamp_mastery_values, migrations.RunPython.noop),
    ]
