from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.recsys.models import TagMastery, Task, TypeMastery
from apps.recsys.services import (
    apply_forgetting_to_tag_masteries,
    recompute_task_difficulties,
    recompute_type_masteries_from_tags,
)


class Command(BaseCommand):
    help = "Recompute MVP recsys periodic state: forgetting, type aggregates, and task difficulty."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            dest="user",
            help="Recompute student-side state for a single user (id or username).",
        )
        parser.add_argument(
            "--tasks-only",
            action="store_true",
            help="Only recompute task difficulty values.",
        )
        parser.add_argument(
            "--students-only",
            action="store_true",
            help="Only recompute student-side forgetting and type aggregates.",
        )

    def _resolve_users(self, user_filter):
        User = get_user_model()
        if not user_filter:
            return User.objects.all()
        if user_filter.isdigit():
            users = User.objects.filter(pk=int(user_filter))
        else:
            users = User.objects.filter(username=user_filter)
        if not users.exists():
            raise CommandError("User not found")
        return users

    def handle(self, *args, **options):
        tasks_only = options["tasks_only"]
        students_only = options["students_only"]
        if tasks_only and students_only:
            raise CommandError("Use either --tasks-only or --students-only, not both.")

        user_filter = options.get("user")
        users = self._resolve_users(user_filter) if user_filter else None

        forgetting_updates = 0
        type_updates = 0
        task_updates = 0

        if not tasks_only:
            if users is None:
                users = self._resolve_users(user_filter)
            user_ids = list(users.values_list("id", flat=True))
            forgetting_updates = apply_forgetting_to_tag_masteries(
                queryset=TagMastery.objects.filter(user_id__in=user_ids)
            )
            type_updates = recompute_type_masteries_from_tags(
                queryset=TypeMastery.objects.filter(user_id__in=user_ids)
            )

        if not students_only:
            if users is not None:
                user_ids = list(users.values_list("id", flat=True))
                task_queryset = Task.objects.filter(attempts__user_id__in=user_ids).distinct()
            else:
                task_queryset = Task.objects.all()
            task_updates = recompute_task_difficulties(queryset=task_queryset)

        self.stdout.write(
            self.style.SUCCESS(
                "Recomputed recsys state "
                f"(tag_forgetting={forgetting_updates}, type_masteries={type_updates}, tasks={task_updates})"
            )
        )
