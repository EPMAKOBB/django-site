from django.core.management.base import BaseCommand

from apps.recsys.models import Subject, Skill, Task, TaskSkill, TaskType


class Command(BaseCommand):
    help = "Seed database with EGE task types, skills, and demo tasks"

    def handle(self, *args, **options):
        subject, _ = Subject.objects.get_or_create(name="EGE", slug="ege")
        for i in range(1, 28):
            task_type, _ = TaskType.objects.get_or_create(
                name=str(i), subject=subject
            )
            skill, _ = Skill.objects.get_or_create(
                name=f"Skill {i}", subject=subject
            )
            task, _ = Task.objects.get_or_create(
                type=task_type,
                title=f"Demo Task {i}",
                defaults={"description": f"Demo task for type {i}"},
            )
            TaskSkill.objects.get_or_create(task=task, skill=skill)
        self.stdout.write(self.style.SUCCESS("EGE data seeded"))
