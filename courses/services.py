from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping, Sequence

from apps.recsys.models import SkillMastery, TypeMastery

from .models import (
    CourseModule,
    CourseModuleItem,
    CourseModuleItemCompletion,
    CourseGraphEdge,
    CourseEnrollment,
)

MODULE_UNLOCK_PROGRESS_THRESHOLD = 30.0


def _clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def get_base_module_mastery_percent(
    user, module: CourseModule, enrollment: CourseEnrollment
) -> float:
    mastery_value: float | None = None

    if module.kind == CourseModule.Kind.SKILL and module.skill_id:
        mastery_value = (
            SkillMastery.objects.filter(user=user, skill=module.skill)
            .values_list("mastery", flat=True)
            .first()
        )
    elif module.kind == CourseModule.Kind.TASK_TYPE and module.task_type_id:
        mastery_value = (
            TypeMastery.objects.filter(user=user, task_type=module.task_type)
            .values_list("mastery", flat=True)
            .first()
        )
    else:
        mastery_value = float(enrollment.progress or 0)

    if mastery_value is None:
        return 0.0

    mastery_percent = float(mastery_value)
    if mastery_percent <= 1.0:
        mastery_percent *= 100.0

    return _clamp_percent(mastery_percent)


def calculate_module_progress_percent(
    *,
    user,
    module: CourseModule,
    enrollment: CourseEnrollment,
    module_items: Sequence[CourseModuleItem] | None = None,
    completed_theory_item_ids: Iterable[int] | None = None,
) -> float:
    if module_items is None:
        module_items = list(module.items.all())

    theory_items = [
        item for item in module_items if item.kind == CourseModuleItem.ItemKind.THEORY
    ]

    if (
        module.kind == CourseModule.Kind.SELF_PACED
        and module_items
        and len(theory_items) == len(module_items)
    ):
        theory_item_ids = [item.id for item in theory_items]
        if completed_theory_item_ids is None:
            completed_theory_item_ids = CourseModuleItemCompletion.objects.filter(
                user=user, module_item_id__in=theory_item_ids
            ).values_list("module_item_id", flat=True)
        completed_ids = set(completed_theory_item_ids)
        completed_count = len(completed_ids.intersection(theory_item_ids))
        if not theory_item_ids:
            return 0.0
        return _clamp_percent(100.0 * completed_count / len(theory_item_ids))

    return get_base_module_mastery_percent(user, module, enrollment)


def build_module_progress_map(
    *,
    user,
    enrollment: CourseEnrollment,
    modules: Sequence[CourseModule],
) -> Mapping[int, float]:
    modules = list(modules)
    module_items_map: dict[int, list[CourseModuleItem]] = {}
    theory_item_ids: list[int] = []
    item_to_module: dict[int, int] = {}

    for module in modules:
        module_items = list(module.items.all())
        module_items_map[module.id] = module_items
        for item in module_items:
            if item.kind == CourseModuleItem.ItemKind.THEORY:
                theory_item_ids.append(item.id)
                item_to_module[item.id] = module.id

    completed_by_module: dict[int, set[int]] = defaultdict(set)
    if theory_item_ids:
        for module_item_id in CourseModuleItemCompletion.objects.filter(
            user=user, module_item_id__in=theory_item_ids
        ).values_list("module_item_id", flat=True):
            module_id = item_to_module.get(module_item_id)
            if module_id is not None:
                completed_by_module[module_id].add(module_item_id)

    progress_map: dict[int, float] = {}
    for module in modules:
        progress_map[module.id] = calculate_module_progress_percent(
            user=user,
            module=module,
            enrollment=enrollment,
            module_items=module_items_map.get(module.id, []),
            completed_theory_item_ids=completed_by_module.get(module.id, set()),
        )

    return progress_map


def is_module_unlocked_for_user(
    *,
    user,
    module: CourseModule,
    enrollment: CourseEnrollment,
    incoming_edges: Iterable[CourseGraphEdge] | None = None,
    progress_map: Mapping[int, float] | None = None,
) -> bool:
    if incoming_edges is None:
        incoming_edges = module.incoming_edges.select_related("src").all()

    relevant_edges = [
        edge for edge in incoming_edges if edge.src is not None and not edge.is_locked
    ]

    for edge in relevant_edges:
        src_progress = None
        if progress_map is not None:
            src_progress = progress_map.get(edge.src_id)

        if src_progress is None:
            src_progress = calculate_module_progress_percent(
                user=user, module=edge.src, enrollment=enrollment
            )

        if src_progress < MODULE_UNLOCK_PROGRESS_THRESHOLD:
            return False

    if relevant_edges:
        return True

    return not module.is_locked
