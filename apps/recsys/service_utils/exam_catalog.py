"""Versioned reference data; never stores users, sessions, CSRF tokens or task pools.

The generation lives in the database so LocMemCache workers see invalidation too.
Bulk imports must call invalidate_exam_catalog() inside their transaction.
"""
from uuid import uuid4

from django.core.cache import cache
from django.http import Http404
from django.utils.text import slugify

from subjects.models import Subject
from apps.recsys.models import (
    ExamBlueprint, ExamBlueprintItem, ExamCatalogRevision, ExamScoreScale,
    ExamVersion, TaskTag, TaskType,
)


def invalidate_exam_catalog(*, using="default"):
    # Write in the caller's transaction: other workers see the generation only
    # after commit, and rollbacks also roll back the invalidation. This avoids
    # publishing uncommitted catalog contents under an older shared cache key.
    ExamCatalogRevision.objects.using(using).update_or_create(
        pk=1, defaults={"generation": uuid4()},
    )


def get_exam_catalog():
    revision, _ = ExamCatalogRevision.objects.get_or_create(pk=1)
    key = f"exam-catalog:v1:{revision.generation}"
    catalog = cache.get(key)
    if catalog is not None:
        return catalog
    subjects = {row["id"]: row for row in Subject.objects.values()}
    exams = {}
    for row in ExamVersion.objects.values():
        row.update(pk=row["id"], subject=subjects[row["subject_id"]])
        exams[row["id"]] = row
    tags = {row["id"]: row for row in TaskTag.objects.values()}
    types = {}
    for row in TaskType.objects.order_by("display_order", "id").values():
        row.update(pk=row["id"], required_tags=[])
        types[row["id"]] = row
    for type_id, tag_id in TaskType.required_tags.through.objects.values_list("tasktype_id", "tasktag_id"):
        types[type_id]["required_tags"].append(tags[tag_id])
    for row in types.values():
        row["required_tags"].sort(key=lambda tag: tag["name"])
    blueprints = {}
    by_blueprint = {}
    for row in ExamBlueprint.objects.filter(is_active=True).values():
        row["items"] = []
        blueprints[row["exam_version_id"]] = row
        by_blueprint[row["id"]] = row
    for row in ExamBlueprintItem.objects.order_by("order", "id").values():
        if row["blueprint_id"] in by_blueprint:
            row["task_type"] = types.get(row["task_type_id"])
            by_blueprint[row["blueprint_id"]]["items"].append(row)
    catalog = {
        "subjects": subjects, "exams": exams, "types": types, "tags": tags,
        "blueprints": blueprints,
        "scales": {row["exam_version_id"]: row for row in ExamScoreScale.objects.filter(is_active=True).values()},
    }
    cache.set(key, catalog, timeout=86400)
    return catalog


def find_exam(catalog, slug):
    exams = catalog["exams"].values()
    exam = next((row for row in exams if row["slug"] == slug), None)
    if exam is None:
        exam = next((row for row in exams if slugify(row["name"]) == slug), None)
    if exam is None:
        raise Http404("Exam not found")
    return exam


def exam_structure(catalog, exam_id):
    blueprint = catalog["blueprints"].get(exam_id)
    if blueprint:
        rows = [{"item": item, "type": item["task_type"], "required_tags": item["task_type"]["required_tags"]}
                for item in blueprint["items"] if item["task_type"]]
    else:
        rows = [{"type": row, "required_tags": row["required_tags"]}
                for row in catalog["types"].values() if row["exam_version_id"] == exam_id]
    return {"blueprint": blueprint, "type_rows": rows}
