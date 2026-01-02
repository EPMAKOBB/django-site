from django.db import migrations, models
from django.utils.text import slugify


def _unique_slug_for_type(task_type, base_slug, model_cls):
    """
    Ensure slug uniqueness within (subject, exam_version).
    """
    if not base_slug:
        base_slug = f"type-{task_type.pk or 'new'}"
    slug = base_slug
    counter = 1
    conflict_exists = lambda s: model_cls.objects.filter(
        subject_id=task_type.subject_id,
        exam_version_id=task_type.exam_version_id,
        slug=s,
    ).exclude(pk=task_type.pk).exists()
    while conflict_exists(slug):
        counter += 1
        slug = f"{base_slug}-{counter}"
    return slug


def populate_tasktype_slugs(apps, schema_editor):
    TaskType = apps.get_model("recsys", "TaskType")
    for task_type in TaskType.objects.all():
        base = slugify(task_type.slug or task_type.name)
        unique_slug = _unique_slug_for_type(task_type, base, TaskType)
        if task_type.slug != unique_slug:
            task_type.slug = unique_slug
            task_type.save(update_fields=["slug"])


class Migration(migrations.Migration):
    dependencies = [
        ("recsys", "0019_retire_informatics_only_schemas"),
    ]

    operations = [
        migrations.AddField(
            model_name="tasktype",
            name="slug",
            field=models.SlugField(
                blank=True,
                help_text="Machine-friendly code, e.g. algebra-basic",
                max_length=128,
                null=True,
            ),
        ),
        migrations.RunPython(populate_tasktype_slugs, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="tasktype",
            constraint=models.UniqueConstraint(
                fields=("subject", "exam_version", "slug"),
                name="task_type_subject_exam_slug_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="tasktype",
            index=models.Index(
                fields=["subject", "exam_version", "slug"],
                name="recsys_tt_subj_exam_slug_idx",
            ),
        ),
    ]
