from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from django.db.models import Q, Sum

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

        for user in users:
            for skill in Skill.objects.all():
                counts = Attempt.objects.filter(user=user, task__skills=skill).aggregate(
                    total=Sum("attempts_count"),
                    correct=Sum("attempts_count", filter=Q(is_correct=True)),
                )
                total = counts["total"] or 0
                correct = counts["correct"] or 0
                mastery = correct / total if total else 0.0
                SkillMastery.objects.update_or_create(
                    user=user, skill=skill, defaults={"mastery": mastery}
                )

            for task_type in TaskType.objects.all():
                counts = Attempt.objects.filter(user=user, task__type=task_type).aggregate(
                    total=Sum("attempts_count"),
                    correct=Sum("attempts_count", filter=Q(is_correct=True)),
                )
                total = counts["total"] or 0
                correct = counts["correct"] or 0
                mastery = correct / total if total else 0.0
                TypeMastery.objects.update_or_create(
                    user=user, task_type=task_type, defaults={"mastery": mastery}
                )

        self.stdout.write(self.style.SUCCESS("Mastery recomputed"))
