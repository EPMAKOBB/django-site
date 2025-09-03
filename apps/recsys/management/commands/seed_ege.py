from django.core.management.base import BaseCommand

from apps.recsys.models import (
    ExamVersion,
    Skill,
    SkillGroup,
    SkillGroupItem,
    Subject,
    Task,
    TaskSkill,
    TaskType,
)


class Command(BaseCommand):
    help = "Seed database with EGE task types, skills, and demo tasks"

    def handle(self, *args, **options):
        subject, _ = Subject.objects.get_or_create(name="Математика")
        for i in range(1, 28):
            task_type, _ = TaskType.objects.get_or_create(name=str(i), subject=subject)
            skill, _ = Skill.objects.get_or_create(name=f"Skill {i}", subject=subject)
            task, _ = Task.objects.get_or_create(
                type=task_type,
                title=f"Demo Task {i}",
                subject=subject,
                defaults={"description": f"Demo task for type {i}"},
            )
            TaskSkill.objects.get_or_create(task=task, skill=skill)
        exam_version, _ = ExamVersion.objects.get_or_create(
            name="ЕГЭ 2026", subject=subject
        )
        groups = {
            "Алгебра": [
                ("Skill 1", "Линейные уравнения"),
                ("Skill 2", "Квадратные уравнения"),
            ],
            "Геометрия": [
                ("Skill 3", "Планиметрия"),
                ("Skill 4", "Стереометрия"),
            ],
        }
        for g_title, items in groups.items():
            group, _ = SkillGroup.objects.get_or_create(
                exam_version=exam_version, title=g_title
            )
            for order, (skill_name, label) in enumerate(items, start=1):
                skill = Skill.objects.get(name=skill_name)
                SkillGroupItem.objects.get_or_create(
                    group=group,
                    skill=skill,
                    defaults={"label": label, "order": order},
                )
        self.stdout.write(self.style.SUCCESS("EGE data seeded"))
