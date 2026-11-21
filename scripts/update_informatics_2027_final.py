"""Prepare and publish the approved 2027 revision without editing issued content.

Run through Django shell (or import run); preview rolls back database changes.
Document hashes and the corrected file are supplied explicitly by the operator.
"""
import hashlib
from copy import deepcopy

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction

from apps.recsys.models import (
    ExamVersion, Task, TaskAttachment, TaskPlacement, TaskTypeTransition,
)
from apps.recsys.service_utils.exam_rollover import create_next_year, publish_exam, validate_rollover

MARKER = "informatics-2027-approved-r2-v1"
TASK_SLUG = "inf-ege-2027-demo-27-approved"
FILE_SHA256 = "ad36710cf8a489ba6e1d79357974f6e6463b98b5225084be78352ab83407597b"
DOCUMENT_HASHES = {
    "ИНФ-11 ЕГЭ 2027 ДЕМО.pdf": "b3e8be2430f9f2283fea169c82b68409ea0d2234b3f2eff98f904ab80d2a57a6",
    "ИНФ-11 ЕГЭ 2027 КОДИФ.pdf": "8f4f913c066d33b4451354d0dd9c5e920eaf7aa000166b80408518d6ef4e178c",
    "ИНФ-11 ЕГЭ 2027 СПЕЦ.pdf": "a70655c652178513983c7a2769a8459bed3e76ec6d6a536588531fcf4a8371d0",
}


def run(*, file_bytes, document_hashes, apply=False, publish=False, verify=None):
    """Apply only the known August -> approved revision; never rewrite revision 1."""
    written = []
    try:
        with transaction.atomic():
            old = ExamVersion.objects.select_for_update().get(slug="inf-ege-2027")
            if old.revision != 1 or old.status != "active" or old.subject.slug != "inf":
                raise ValidationError("Expected active informatics 2027 revision 1.")
            fingerprint = hashlib.sha256(file_bytes).hexdigest()
            if fingerprint != FILE_SHA256 or document_hashes != DOCUMENT_HASHES:
                raise ValidationError("Files differ from the reviewed approved documents.")
            existing = ExamVersion.objects.filter(subject=old.subject, year=2027, exam_kind="ege", revision=2).first()
            if existing:
                if existing.publication_info.get("approved_revision") != MARKER or existing.publication_info.get("document_hashes") != document_hashes or existing.publication_info.get("demo27_sha256") != fingerprint:
                    raise ValidationError("Revision 2 already exists with different provenance.")
                return {"already_prepared": True, "slug": existing.slug, "status": existing.status}
            original = {t.slug: t for t in old.task_types.all()}
            if ("сет" not in original["10"].description.lower() or "исполнител" not in original["13"].description.lower() or "граф" not in original["23"].description.lower()):
                raise ValidationError("Unexpected source catalog.")
            legacy = ExamVersion.objects.get(subject=old.subject, slug="inf-ege-2026", revision=1)
            exam = create_next_year(old, year=2027, new_revision=True)
            types = {t.slug: t for t in exam.task_types.all()}
            # Only newly created draft assignments are discarded.
            TaskPlacement.objects.filter(task_type__in=[types[n] for n in ("10", "13", "23")]).delete()
            exam.type_transitions.all().delete()
            mapping = {"10": legacy.task_types.get(slug="10"), "13": original["10"], "23": original["13"]}
            for number, source in mapping.items():
                target = types[number]
                for field in ("description", "answer_schema", "scoring_scheme", "max_score"):
                    setattr(target, field, getattr(source, field))
                target.save()
                target.required_tags.set(source.required_tags.all())
                target.allowed_tags.set(source.allowed_tags.all())
            for number, target in types.items():
                if number == "27":
                    source = original[number]
                    # Replace the adapted August demo in NEW issuance only.
                    TaskPlacement.objects.filter(task_type=target, task__slug="inf-ege-2027-demo-27-adapted").delete()
                    selected = list(TaskPlacement.objects.filter(task_type=source, status="active").exclude(task__slug="inf-ege-2027-demo-27-adapted").values_list("task_id", flat=True))
                    TaskTypeTransition.objects.create(target_exam=exam, source_type=source, target_type=target,
                        relation="partial", task_ids=selected, allow_empty_source_pool=not selected, approved=True,
                        notes="August adapted demo replaced by corrected approved file; old issued tasks preserved.")
                else:
                    TaskTypeTransition.objects.create(target_exam=exam, source_type=mapping.get(number, original[number]), target_type=target, approved=True)
            TaskTypeTransition.objects.create(target_exam=exam, source_type=original["23"], relation="removed", approved=True,
                notes="Graph position withdrawn in approved specification.")
            adapted = Task.objects.get(slug="inf-ege-2027-demo-27-adapted")
            description = adapted.description
            if "**Если минимум" in description:
                description = description.split("\n\n", 1)[1]
                start = description.index("**Если минимум")
                end = description.index("**", start + 2) + 2
                description = description[:start] + "Для каждого кластера гарантируется единственность его центра." + description[end:]
            elif "гарантируется единственность его центра" not in " ".join(description.split()):
                raise ValidationError("Unexpected adapted demo text.")
            task = Task.objects.create(subject=old.subject, exam_version=exam, type=types["27"],
                slug=TASK_SLUG, title="Демоверсия ЕГЭ 2027. Задание 27 — утверждённая редакция",
                description=description, correct_answer=deepcopy(adapted.correct_answer),
                rendering_strategy=adapted.rendering_strategy, status="published", scoring_scheme="ege_pairs_2027", max_score=2)
            task.tags.set(adapted.tags.all())
            from apps.recsys.models import Source
            source = Source.objects.create(name="ФИПИ — Информатика ЕГЭ 2027, утверждённая редакция", slug="fipi-inf-2027-approved-r2",
                exam_version=exam, description="Утверждённые демоверсия, спецификация и кодификатор; проверка 16.11.2026.")
            task.source = source
            task.save(update_fields=["source"])
            TaskPlacement.objects.create(task=task, task_type=types["27"], status="draft", scoring_scheme="ege_pairs_2027", max_score=2, answer_schema=types["27"].answer_schema)
            if apply:
                attachment = TaskAttachment(task=task, kind="file", download_name_override="demo_27.txt")
                attachment.file.save("demo_27.txt", ContentFile(file_bytes), save=False)
                written.append((attachment.file.storage, attachment.file.name))
                attachment.save()
            exam.publication_info = {"approved_revision": MARKER, "document_hashes": document_hashes,
                "demo27_sha256": fingerprint, "source_document": "Утверждённые документы ФИПИ ЕГЭ 2027; проверка 16.11.2026; СПЕЦ раздел 11, стр.13.",
                "requirements_checked": True, "scale_checked": True, "limitations": ["Шкала перевода отключена"]}
            exam.save()
            report = validate_rollover(exam)
            if report["errors"]:
                raise ValidationError(report["errors"])
            moved = 0
            if publish:
                exam = publish_exam(exam, make_default=True)
                # Preserve old work and change only the preference for future issuance.
                for profile in old.students_preparing.all():
                    profile.exam_versions.add(exam)
                    profile.exam_versions.remove(old)
                    moved += 1
            result = {"slug": exam.slug, "id": exam.pk, "status": exam.status, "applied": apply,
                "warnings": report["warnings"], "profiles_switched": moved,
                "task27": task.pk, "types": report["type_rows"], "can_build_variant": report["can_build_variant"]}
            if verify:
                result["verification"] = verify(exam)
            if not apply:
                transaction.set_rollback(True)
            return result
    except Exception:
        for storage, name in written:
            storage.delete(name)
        raise
