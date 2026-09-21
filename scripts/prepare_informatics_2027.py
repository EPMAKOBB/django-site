"""Reproducible sandbox scenario requested on 2026-09-19; never publishes a year.

Run from the repository root with --apply to retain the draft changes. Without
--apply the entire preparation is rolled back. Actual school data stays local.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

SCENARIO = "informatics-2027-types-10-13-23-v1"


def prepare_transition(source, *, source_document):
    from django.core.exceptions import ValidationError
    from django.db import transaction
    from apps.recsys.models import (
        ExamBlueprint, ExamVersion, Task, TaskPlacement, TaskTag,
        TaskTypeTransition, VariantTask,
    )
    from apps.recsys.service_utils.exam_rollover import create_next_year

    with transaction.atomic():
        target = create_next_year(source, year=2027)
        if target.published_at or target.status != ExamVersion.Status.DRAFT:
            raise ValidationError("Для проверки нужен неопубликованный черновик 2027.")
        if target.publication_info.get("preparation_scenario") == SCENARIO:
            return target
        rows = {row.source_type.slug: row for row in target.type_transitions.select_related("source_type", "target_type") if row.source_type_id}
        if not {"10", "13", "23"}.issubset(rows):
            raise ValidationError("В исходном экзамене нужны типы со slug 10, 13 и 23.")
        if target.type_transitions.count() != source.task_types.count():
            raise ValidationError("Черновик уже изменён: нужно отдельно проверить его соответствия.")
        # Do not overwrite a season edited or used by someone after initial cloning.
        for row in rows.values():
            old, new = row.source_type, row.target_type
            if not new or row.approved or row.relation != "equivalent" or row.task_ids or row.notes:
                raise ValidationError("Черновик уже проверялся или редактировался; автоматическая замена остановлена.")
            fields = ("name", "slug", "description", "display_order", "answer_schema_id", "scoring_scheme", "max_score")
            if any(getattr(old, key) != getattr(new, key) for key in fields) or set(old.required_tags.all()) != set(new.required_tags.all()):
                raise ValidationError("Типы черновика уже изменены; требуется ручное сопоставление.")
        if TaskPlacement.objects.filter(task_type__exam_version=target).exclude(status="draft").exists():
            raise ValidationError("В черновике уже изменена доступность назначений.")

        removed_row, network_row, executor_row = (rows[key] for key in ("10", "13", "23"))
        removed_type = removed_row.target_type
        if removed_type.recorded_attempts.exists() or Task.objects.filter(type=removed_type).exists() or VariantTask.objects.filter(placement__task_type=removed_type).exists():
            raise ValidationError("Черновой тип 10 уже использован; менять его назначение нельзя.")
        # The unused cloned row is repurposed for the new graph type. Only its
        # unissued draft placements are removed; the entire 2026 bank is retained.
        TaskPlacement.objects.filter(task_type=removed_type).delete()
        removed_row.target_type = None
        removed_row.relation = TaskTypeTransition.Relation.REMOVED
        removed_row.approved = True
        removed_row.notes = "По пользовательскому сценарию: текстовый поиск исключён из 2027; история 2026 сохраняется."
        removed_row.save()

        # Free both unique name and slug before rotating the three type numbers.
        removed_type.name = f"Черновая перестановка {removed_type.pk}"
        removed_type.slug = f"transition-{removed_type.pk}"
        removed_type.save()

        network = network_row.target_type
        network.name, network.slug, network.display_order = "тип 10", "10", 10
        network.save()
        executor = executor_row.target_type
        executor.name, executor.slug, executor.display_order = "тип 13", "13", 13
        executor.description = "Анализ программ исполнителя: преобразование чисел"
        executor.save()
        digit_tag, _ = TaskTag.objects.get_or_create(subject=source.subject, name="Замена цифр", defaults={"slug": "digit-replacement"})
        executor.required_tags.add(digit_tag)
        executor_row.relation = TaskTypeTransition.Relation.PARTIAL
        executor_row.task_ids = sorted(TaskPlacement.objects.filter(task_type=executor_row.source_type, status="active").values_list("task_id", flat=True))
        executor_row.notes = "Прежние задачи и темы сохранены. Новая тема «Замена цифр» требует отдельных задач и подтверждения знаний."

        removed_type.name, removed_type.slug, removed_type.display_order = "тип 23", "23", 23
        removed_type.description = "Длина пути в ориентированном графе. Разновидности и требования ещё не определены."
        removed_type.answer_schema = None
        removed_type.scoring_scheme = "binary"
        removed_type.max_score = 1
        removed_type.save()
        removed_type.required_tags.clear()
        TaskTypeTransition.objects.create(target_exam=target, target_type=removed_type, relation="added", approved=True,
                                         notes="Новый тип без переноса прежних ответов. Нет банка задач и утверждённых разновидностей.")
        for row in rows.values():
            if row.pk == removed_row.pk:
                continue
            row.approved = True
            if not row.notes:
                row.notes = "Соответствие сохранено по пользовательскому сценарию; полная методическая проверка сезона отдельно."
            row.save()

        for bp in ExamBlueprint.objects.filter(exam_version=target):
            items = {item.task_type_id: item for item in bp.items.all()}
            if not {removed_type.pk, network.pk, executor.pk}.issubset(items):
                raise ValidationError("В структуре черновика отсутствуют изменяемые типы.")
            # Break the 10 -> 23 -> 13 -> 10 permutation without violating UNIQUE.
            item = items[removed_type.pk]
            item.order = max(i.order for i in items.values()) + 1
            item.save()
            for typ, order in ((network, 10), (executor, 13), (removed_type, 23)):
                item = items[typ.pk]
                item.order = order
                item.save()

        target.publication_info = {
            **target.publication_info,
            "preparation_scenario": SCENARIO,
            "source_document": source_document,
            "requirements_checked": False,
            "scale_checked": False,
            "pending_review": ["Задачи для темы «Замена цифр»", "Требования и банк нового типа 23", "Изменение формата ответа типа 27 в спецификации 2027", "Полная проверка остальных типов и шкалы"],
        }
        target.save()
        return target


def retained_data_fingerprint(source):
    """Hash facts and the source-year bank without writing personal data to reports."""
    from django.core.serializers.json import DjangoJSONEncoder
    from apps.recsys.models import (
        Attempt, Task, TaskType, TaskPlacement, VariantAttempt, VariantTaskAttempt,
        TrainingSession, TrainingSessionStep, ExamProgressSnapshot,
        TypeMastery, TagMastery, SkillMastery, ExamBlueprintItem, ExamScoreScale,
    )
    result = {}
    queries = {
        "tasks": Task.objects.all(), "attempts": Attempt.objects.all(),
        "variant_attempts": VariantAttempt.objects.all(), "variant_task_attempts": VariantTaskAttempt.objects.all(),
        "training_steps": TrainingSessionStep.objects.all(), "progress_snapshots": ExamProgressSnapshot.objects.all(),
        "training_sessions": TrainingSession.objects.all(),
        "type_masteries": TypeMastery.objects.all(), "tag_masteries": TagMastery.objects.all(), "skill_masteries": SkillMastery.objects.all(),
        "source_blueprint": ExamBlueprintItem.objects.filter(blueprint__exam_version=source),
        "source_scale": ExamScoreScale.objects.filter(exam_version=source),
        "source_types": TaskType.objects.filter(exam_version=source),
        "source_placements": TaskPlacement.objects.filter(task_type__exam_version=source),
        "task_tags": Task.tags.through.objects.all(),
        "source_required_tags": TaskType.required_tags.through.objects.filter(tasktype__exam_version=source),
    }
    for label, qs in queries.items():
        digest, count = hashlib.sha256(), 0
        for row in qs.order_by("pk").values().iterator(chunk_size=250):
            digest.update(json.dumps(row, sort_keys=True, cls=DjangoJSONEncoder).encode())
            count += 1
        result[label] = {"count": count, "sha256": digest.hexdigest()}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", default=".local/exam-sandbox/transition-2027/preparation.json")
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ["DJANGO_SETTINGS_MODULE"] = "fractalschool.exam_sandbox_settings"
    import django
    django.setup()
    from django.conf import settings
    from django.db import transaction
    from apps.recsys.models import ExamVersion, TaskPlacement
    from apps.recsys.service_utils.exam_rollover import validate_rollover
    db = settings.DATABASES["default"]
    if (db["HOST"], str(db["PORT"]), db["NAME"]) != ("127.0.0.1", "55438", "exam_year_sandbox"):
        raise RuntimeError("Этот сценарий разрешён только в локальной exam_year_sandbox.")
    with transaction.atomic():
        source = ExamVersion.objects.get(slug="inf-ege-2026")
        before = retained_data_fingerprint(source)
        target = prepare_transition(source, source_document="Пользовательский сценарий 19.09.2026; проект ФИПИ от 21.08.2026, СПЕЦ 2027, раздел 11; ДЕМО 2027, задания 13 и 23.")
        after = retained_data_fingerprint(source)
        if before != after:
            raise RuntimeError("Изменились сохраняемые факты или исходный банк; транзакция отменена.")
        report = {"applied": args.apply, "source_exam_id": source.pk, "target_exam_id": target.pk, "target_slug": target.slug,
                  "before": before, "after": after, "retained_data_unchanged": True, "validation": validate_rollover(target),
                  "types": [{"id": t.pk, "slug": t.slug, "description": t.description, "tags": list(t.required_tags.values_list("name", flat=True)),
                             "placements": TaskPlacement.objects.filter(task_type=t).count()} for t in target.task_types.filter(slug__in=["10", "13", "23"])],
                  "pending_review": target.publication_info["pending_review"]}
        if not args.apply:
            transaction.set_rollback(True)
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("applied", "target_exam_id", "retained_data_unchanged", "types")}, ensure_ascii=False, indent=2))
    print("Publication ready:", report["validation"]["ready"], "Report:", path)


if __name__ == "__main__":
    main()
