"""Показывает экзамены, связанные с профилем студента.

Пример использования:
    python manage.py show_student_exams --username=username
"""

from django.core.management.base import BaseCommand

from accounts.models import StudentProfile


class Command(BaseCommand):
    help = "Отображает список экзаменов, к которым привязан студент."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--username",
            dest="username",
            help="Имя пользователя студента",
        )
        group.add_argument(
            "--email",
            dest="email",
            help="Email пользователя студента",
        )

    def handle(self, *args, **options):
        lookup = {}
        identifier = options.get("username") or options.get("email") or ""

        if options.get("username"):
            lookup["user__username"] = options["username"]
        else:
            lookup["user__email"] = options["email"]

        try:
            profile = (
                StudentProfile.objects.select_related("user")
                .prefetch_related("exam_versions__subject")
                .get(**lookup)
            )
        except StudentProfile.DoesNotExist:
            self.stderr.write(
                self.style.ERROR(
                    "Студент с указанными данными не найден: %s" % identifier
                )
            )
            return

        exam_versions = profile.exam_versions.all()
        if not exam_versions:
            self.stdout.write(
                self.style.WARNING(
                    f"У студента {profile.user.get_username()} нет назначенных экзаменов."
                )
            )
            return

        self.stdout.write(
            f"Экзамены студента {profile.user.get_username()} ({profile.user.email}):"
        )
        for exam_version in exam_versions:
            subject_name = getattr(exam_version.subject, "name", "Без предмета")
            self.stdout.write(
                f" - {exam_version.id}: {subject_name} / {exam_version.name}"
            )
