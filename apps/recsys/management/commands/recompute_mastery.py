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
        parser.add_argument("--legacy-ratio", action="store_true", help="Explicit compatibility mode: use the old correct/total estimator.")
        parser.add_argument("--as-of", help="ISO timestamp for deterministic forgetting; must not precede the last answer.")
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

        if not options["legacy_ratio"]:
            from django.utils import timezone
            from django.utils.dateparse import parse_datetime
            from django.core.exceptions import ValidationError
            from apps.recsys.service_utils.rebuild_learning import rebuild_learning_state
            now = parse_datetime(options["as_of"]) if options.get("as_of") else timezone.now()
            if now is None:
                raise CommandError("Invalid --as-of timestamp")
            if timezone.is_naive(now):
                now = timezone.make_aware(now)
            for user in users:
                try:
                    rebuild_learning_state(user, now=now)
                except ValidationError as exc:
                    raise CommandError("; ".join(exc.messages)) from exc
            self.stdout.write(self.style.SUCCESS("Mastery rebuilt with event-learning-v1; answer records unchanged"))
            return

        for user in users:
            for skill in Skill.objects.all():
                counts = Attempt.objects.filter(user=user, task__skills=skill).aggregate(
                    total=Count("id"),
                    correct=Count("id", filter=Q(is_correct=True)),
                )
                total, correct = counts["total"], counts["correct"]
                mastery = correct / total if total else 0.0
                SkillMastery.objects.update_or_create(
                    user=user, skill=skill, defaults={"mastery": mastery}
                )

            for task_type in TaskType.objects.all():
                counts = Attempt.objects.filter(user=user, task_type=task_type).aggregate(
                    total=Count("id"),
                    correct=Count("id", filter=Q(is_correct=True)),
                )
                total, correct = counts["total"], counts["correct"]
                mastery = correct / total if total else 0.0
                TypeMastery.objects.update_or_create(
                    user=user, task_type=task_type, defaults={"mastery": mastery}
                )

        self.stdout.write(self.style.SUCCESS("Mastery recomputed"))
