from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from django.db.models import Count, Q

from apps.recsys.models import (
    Attempt,
    Skill,
    SkillMastery,
    TaskType,
    TypeMastery,
)


class Command(BaseCommand):
    help = "Recompute mastery values from attempts"

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            dest="user",
            help="Recompute mastery for a single user (id or username)",
        )
        parser.add_argument(
            "--exam-version",
            dest="exam_version",
            type=int,
            help="Limit recomputation to a specific exam version",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        user_filter = options.get("user")

        if user_filter:
            if user_filter.isdigit():
                users = User.objects.filter(pk=int(user_filter))
            else:
                users = User.objects.filter(username=user_filter)
            if not users.exists():
                raise CommandError("User not found")
        else:
            users = User.objects.all()

        exam_version = options.get("exam_version")

        for user in users:
            skills = Skill.objects.all()
            task_types = TaskType.objects.all()
            if exam_version:
                skills = skills.filter(exam_version_id=exam_version)
                task_types = task_types.filter(exam_version_id=exam_version)

            for skill in skills:
                counts = Attempt.objects.filter(user=user, task__skills=skill).aggregate(
                    total=Count("id"),
                    correct=Count("id", filter=Q(is_correct=True)),
                )
                total, correct = counts["total"], counts["correct"]
                mastery = correct / total if total else 0.0
                SkillMastery.objects.update_or_create(
                    user=user, skill=skill, defaults={"mastery": mastery}
                )

            for task_type in task_types:
                counts = Attempt.objects.filter(user=user, task__type=task_type).aggregate(
                    total=Count("id"),
                    correct=Count("id", filter=Q(is_correct=True)),
                )
                total, correct = counts["total"], counts["correct"]
                mastery = correct / total if total else 0.0
                TypeMastery.objects.update_or_create(
                    user=user, task_type=task_type, defaults={"mastery": mastery}
                )

        self.stdout.write(self.style.SUCCESS("Mastery recomputed"))
