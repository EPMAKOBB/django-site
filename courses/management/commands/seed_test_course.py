from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from courses.models import (
    Course,
    CourseEnrollment,
    CourseGraphEdge,
    CourseLayout,
    CourseModule,
    CourseModuleItem,
    CourseTheoryCard,
)


class Command(BaseCommand):
    help = "Создает тестовый курс с модулями и материалами для визуальной проверки интерфейса"

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            default="student",
            help="Имя пользователя, которого записать на курс (будет создан при отсутствии)",
        )
        parser.add_argument(
            "--password",
            default="testpass123",
            help="Пароль для пользователя (используется при создании)",
        )
        parser.add_argument(
            "--slug",
            default="test-fractals",
            help="Слаг курса",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        username: str = options["username"]
        password: str = options["password"]
        slug: str = options["slug"]

        User = get_user_model()

        user, created = User.objects.get_or_create(
            username=username, defaults={"email": "", "is_active": True}
        )
        if created:
            user.set_password(password)
            user.save(update_fields=["password"])

        course, _ = Course.objects.update_or_create(
            slug=slug,
            defaults={
                "title": "Введение в фракталы",
                "subtitle": "От простых правил — к бесконечным узорам",
                "short_description": "Быстрый обзор основных идей фрактальной геометрии на наглядных примерах.",
                "full_description": (
                    "Курс знакомит с ключевыми понятиями: самоподобие, множество Мандельброта, L-системы. "
                    "Каждый модуль содержит теорию и шаги для самостоятельного изучения."
                ),
                "level": Course.Level.BEGINNER,
                "language": Course.Language.RU,
                "duration_weeks": 2,
                "is_active": True,
                "enrollment_open": True,
            },
        )

        # Обеспечим наличие layout с дефолтными брейкпоинтами
        CourseLayout.objects.get_or_create(course=course, defaults={"preset_name": "grid-3"})

        # Очистим связанные сущности, чтобы команда была идемпотентной
        CourseModuleItem.objects.filter(module__course=course).delete()
        CourseGraphEdge.objects.filter(course=course).delete()
        CourseTheoryCard.objects.filter(course=course).delete()
        CourseModule.objects.filter(course=course).delete()

        # Создадим модули (self-paced, чтобы не зависеть от recsys)
        modules_spec = [
            {
                "slug": "intro",
                "title": "Что такое фрактал",
                "subtitle": "Самоподобие и бесконечная детализация",
                "description": "Понятие самоподобия, исторические примеры и визуальные свойства.",
                "rank": 1,
                "col": 1,
                "dx": 0,
                "dy": 0,
            },
            {
                "slug": "mandelbrot",
                "title": "Множество Мандельброта",
                "subtitle": "Комплексная плоскость под лупой",
                "description": "Интуитивное объяснение и геометрические особенности множества.",
                "rank": 2,
                "col": 2,
                "dx": 0,
                "dy": 0,
            },
            {
                "slug": "l-systems",
                "title": "L-системы и деревья",
                "subtitle": "Как формальные правила рождают рисунки",
                "description": "Основы L-систем и генерация ветвящихся структур.",
                "rank": 3,
                "col": 3,
                "dx": 0,
                "dy": 0,
            },
        ]

        modules: dict[str, CourseModule] = {}
        for spec in modules_spec:
            module = CourseModule.objects.create(
                course=course,
                slug=spec["slug"],
                title=spec["title"],
                subtitle=spec["subtitle"],
                description=spec["description"],
                kind=CourseModule.Kind.SELF_PACED,
                rank=spec["rank"],
                col=spec["col"],
                dx=spec["dx"],
                dy=spec["dy"],
                is_locked=False,
            )
            modules[spec["slug"]] = module

        # Теоретические карточки и элементы модулей
        def add_theory(module: CourseModule, slug: str, title: str, content: str, position: int):
            card = CourseTheoryCard.objects.create(
                course=course,
                slug=slug,
                title=title,
                subtitle="",
                content=content,
                content_format=CourseTheoryCard.ContentFormat.MARKDOWN,
                estimated_duration_minutes=5,
                difficulty_level=10,
            )
            CourseModuleItem.objects.create(
                module=module,
                kind=CourseModuleItem.ItemKind.THEORY,
                theory_card=card,
                position=position,
                min_mastery_percent=0,
                max_mastery_percent=100,
            )

        add_theory(
            modules["intro"],
            slug="fractal-definition",
            title="Определение и свойства",
            content=(
                "Фрактал — это структура, обладающая самоподобием на разных масштабах.\n\n"
                "Ключевые свойства:\n\n"
                "- Самоподобие (точное или статистическое)\n"
                "- Дробная размерность\n"
                "- Бесконечная детализация\n"
            ),
            position=1,
        )
        add_theory(
            modules["intro"],
            slug="fractal-history",
            title="Коротко об истории",
            content=(
                "От Кантора и Пеано к Мандельброту: как развивались идеи,\n"
                "приведшие к формированию фрактальной геометрии."
            ),
            position=2,
        )

        add_theory(
            modules["mandelbrot"],
            slug="mandelbrot-basics",
            title="Базовая идея множества",
            content=(
                "Множество Мандельброта определяется по итерации z_{n+1} = z_n^2 + c.\n\n"
                "Точки c, для которых последовательность не уходит на бесконечность,\n"
                "образуют знаменитую границу с бесконечной сложностью."
            ),
            position=1,
        )
        add_theory(
            modules["mandelbrot"],
            slug="mandelbrot-zoom",
            title="Приближения и самоподобие",
            content=(
                "При увеличении границы появляются знакомые узоры и мини-копии фигуры."
            ),
            position=2,
        )

        add_theory(
            modules["l-systems"],
            slug="lsystems-intro",
            title="Идея L-систем",
            content=(
                "L-системы задают правила переписывания строк, по которым строятся геометрические фигуры."
            ),
            position=1,
        )
        add_theory(
            modules["l-systems"],
            slug="lsystems-trees",
            title="Фрактальные деревья",
            content=(
                "Простые правила разветвления порождают реалистичные деревья и лиственные структуры."
            ),
            position=2,
        )

        # Рёбра графа (последовательное прохождение)
        CourseGraphEdge.objects.create(
            course=course, src=modules["intro"], dst=modules["mandelbrot"], kind="sequence"
        )
        CourseGraphEdge.objects.create(
            course=course, src=modules["mandelbrot"], dst=modules["l-systems"], kind="sequence"
        )

        # Запишем пользователя на курс
        enrollment, _ = CourseEnrollment.objects.get_or_create(
            course=course,
            student=user,
            defaults={
                "status": CourseEnrollment.Status.ENROLLED,
                "progress": Decimal("25.0"),
            },
        )

        self.stdout.write(self.style.SUCCESS("Тестовый курс успешно подготовлен."))
        self.stdout.write(
            f"Курс: {course.title} (/{course.slug}) | Модулей: {CourseModule.objects.filter(course=course).count()}"
        )
        self.stdout.write(
            f"Пользователь: {user.username} | Запись на курс: {enrollment.get_status_display()} | Прогресс: {enrollment.progress}%"
        )
        self.stdout.write(
            "Откройте страницу: /accounts/dashboard/courses/ (после входа пользователем)"
        )

