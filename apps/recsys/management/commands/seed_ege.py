from copy import deepcopy

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from apps.recsys.models import (
    ExamVersion,
    Skill,
    SkillGroup,
    SkillGroupItem,
    Task,
    TaskSkill,
    TaskType,
)
from courses.models import Course, CourseGraphEdge, CourseLayout, CourseModule
from subjects.models import Subject


class Command(BaseCommand):
    help = "Seed database with EGE task types, skills, and demo tasks"

    def handle(self, *args, **options):
        subject, _ = Subject.objects.get_or_create(name="Математика")
        exam_version, _ = ExamVersion.objects.get_or_create(
            name="ЕГЭ 2026", subject=subject
        )
        for i in range(1, 28):
            task_type, _ = TaskType.objects.get_or_create(
                name=str(i),
                subject=subject,
                exam_version=exam_version,
                defaults={"display_order": i, "slug": slugify(str(i))},
            )
            if not task_type.slug:
                task_type.slug = slugify(task_type.name) or f"type-{task_type.pk}"
                task_type.save(update_fields=["slug"])
            if task_type.display_order != i:
                task_type.display_order = i
                task_type.save(update_fields=["display_order"])
            skill, _ = Skill.objects.get_or_create(name=f"Skill {i}", subject=subject)
            task, _ = Task.objects.get_or_create(
                type=task_type,
                title=f"Demo Task {i}",
                subject=subject,
                exam_version=exam_version,
                defaults={"description": f"Demo task for type {i}"},
            )
            TaskSkill.objects.get_or_create(task=task, skill=skill)
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
        default_breakpoints = CourseLayout.DEFAULT_BREAKPOINTS
        for course in Course.objects.all():
            layout_defaults = {
                "preset_name": "default",
                "row_h": 60,
                "col_w": 60,
                "margin_x": 24,
                "margin_y": 24,
                "node_r": 24,
                "breakpoints": deepcopy(default_breakpoints),
            }
            CourseLayout.objects.get_or_create(course=course, defaults=layout_defaults)

            modules = CourseModule.objects.filter(course=course).order_by("rank", "col", "pk")
            previous_module = None
            for module in modules:
                if previous_module and not CourseGraphEdge.objects.filter(
                    course=course, src=previous_module, dst=module
                ).exists():
                    CourseGraphEdge.objects.create(
                        course=course,
                        src=previous_module,
                        dst=module,
                        kind="sequential",
                        weight=1,
                    )
                previous_module = module

        self.stdout.write(self.style.SUCCESS("EGE data seeded"))
