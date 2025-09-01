from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

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
                attempts = Attempt.objects.filter(user=user, task__skills=skill)
                total = attempts.count()
                correct = attempts.filter(is_correct=True).count()
                mastery = correct / total if total else 0.0
                SkillMastery.objects.update_or_create(
                    user=user, skill=skill, defaults={"mastery": mastery}
                )

            for task_type in TaskType.objects.all():
                attempts = Attempt.objects.filter(user=user, task__type=task_type)
                total = attempts.count()
                correct = attempts.filter(is_correct=True).count()
                mastery = correct / total if total else 0.0
                TypeMastery.objects.update_or_create(
                    user=user, task_type=task_type, defaults={"mastery": mastery}
                )

        self.stdout.write(self.style.SUCCESS("Mastery recomputed"))
