import os
import sys
from pathlib import Path

# Ensure project root is on sys.path and Django is configured
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fractalschool.settings")

import django  # noqa: E402

django.setup()

from django.db import transaction  # noqa: E402
from django.utils.text import slugify  # noqa: E402

from subjects.models import Subject  # noqa: E402
from apps.recsys.models import ExamVersion, TaskType, Task  # noqa: E402


def get_informatics_subject():
    # Prefer slug if present, fallback to name
    try:
        return Subject.objects.get(slug="inf")
    except Subject.DoesNotExist:
        try:
            return Subject.objects.get(name__iexact="информатика")
        except Subject.DoesNotExist:
            raise SystemExit("Не найден предмет 'информатика' (slug=inf)")


def get_exam_version(subject):
    name = "Информатика ЕГЭ 2026"
    exam, _ = ExamVersion.objects.get_or_create(subject=subject, name=name)
    return exam


def get_task_type(subject, exam):
    # Try exact match by subject + name + exam_version
    qs = TaskType.objects.filter(subject=subject, name="тип 1", exam_version=exam)
    if qs.exists():
        return qs.first()

    # Fallback: subject + name only (legacy data), pick one if unique
    fallback_qs = TaskType.objects.filter(subject=subject, name="тип 1")
    if fallback_qs.count() == 1:
        return fallback_qs.first()

    # Otherwise create specifically for this exam version
    return TaskType.objects.create(subject=subject, exam_version=exam, name="тип 1")


def build_markdown_statement():
    # Problem statement with a table and an inline SVG bar chart
    return (
        """
Задание. В таблице приведены данные о количестве решённых задач пятью учениками.
На рисунке ниже представлена столбчатая диаграмма (SVG), построенная по тем же данным.
Определите, сколько учеников из города «М» решили не менее 4 задач.

Таблица данных:

| Ученик | Задачи | Город |
|--------|--------|-------|
| A      | 2      | К     |
| B      | 5      | М     |
| C      | 3      | К     |
| D      | 1      | Н     |
| E      | 4      | М     |

Подсказка: по таблице видно, что у учеников B и E из города «М» значения 5 и 4 соответственно.

Диаграмма (SVG):

```svg
<svg width="360" height="150" viewBox="0 0 360 150" xmlns="http://www.w3.org/2000/svg">
  <style>
    .axis { stroke: #555; stroke-width: 1; }
    .bar { fill: #4CAF50; }
    .label { font: 12px sans-serif; fill: #333; }
  </style>
  <!-- axes -->
  <line class="axis" x1="40" y1="130" x2="340" y2="130" />
  <line class="axis" x1="40" y1="20" x2="40" y2="130" />

  <!-- bars: A=2, B=5, C=3, D=1, E=4 -->
  <!-- scale: 1 задача = 20px высоты -->
  <rect class="bar" x="60"  y="130-40" width="30" height="40" />   <!-- A: 2*20 -->
  <rect class="bar" x="110" y="130-100" width="30" height="100" /> <!-- B: 5*20 -->
  <rect class="bar" x="160" y="130-60" width="30" height="60" />  <!-- C: 3*20 -->
  <rect class="bar" x="210" y="130-20" width="30" height="20" />  <!-- D: 1*20 -->
  <rect class="bar" x="260" y="130-80" width="30" height="80" />  <!-- E: 4*20 -->

  <!-- labels -->
  <text class="label" x="75"  y="145" text-anchor="middle">A</text>
  <text class="label" x="125" y="145" text-anchor="middle">B</text>
  <text class="label" x="175" y="145" text-anchor="middle">C</text>
  <text class="label" x="225" y="145" text-anchor="middle">D</text>
  <text class="label" x="275" y="145" text-anchor="middle">E</text>
</svg>
```

Ответ введите одним числом.
"""
    ).strip()


def main():
    subject = get_informatics_subject()
    exam = get_exam_version(subject)
    task_type = get_task_type(subject, exam)

    title = "Тип 1. Таблица и диаграмма (тестовая)"
    description = build_markdown_statement()

    # Unique key: (subject, exam_version, type, title)
    existing = Task.objects.filter(
        subject=subject, exam_version=exam, type=task_type, title=title
    ).first()
    if existing:
        print(f"Уже существует задача id={existing.id}")
        return

    with transaction.atomic():
        task = Task(
            subject=subject,
            exam_version=exam,
            type=task_type,
            title=title,
            description=description,
            is_dynamic=False,
            generator_slug="",
            default_payload={},
            correct_answer={"answer": "2"},  # B и E из города «М»
            difficulty_level=0,
        )
        task.full_clean()
        task.save()

    print(f"Создана задача id={task.id}")


if __name__ == "__main__":
    main()

