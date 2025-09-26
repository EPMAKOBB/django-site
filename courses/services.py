"""Course-related service helpers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List

from django.db.models import Prefetch

from .models import Course, CourseEnrollment, CourseGraphEdge, CourseLayout, CourseModule
from apps.recsys.models import SkillMastery, TypeMastery


@dataclass(frozen=True)
class SerializedEdge:
    id: int
    src: int
    dst: int
    locked: bool
    kind: str
    weight: float


@dataclass(frozen=True)
class SerializedNode:
    id: int
    slug: str
    title: str
    subtitle: str
    description: str
    kind: str
    mastery: float
    locked: bool
    rank: int
    col: int
    dx: int
    dy: int
    incoming: List[int]
    outgoing: List[int]


def _to_percent(value: float | None) -> float:
    if value is None:
        return 0.0
    percent = float(value)
    if percent <= 1.0:
        percent *= 100.0
    return max(0.0, min(percent, 100.0))


def _load_mastery_maps(user, modules: Iterable[CourseModule]) -> tuple[dict[int, float], dict[int, float]]:
    skill_ids = {module.skill_id for module in modules if module.skill_id}
    type_ids = {module.task_type_id for module in modules if module.task_type_id}

    skill_masteries: dict[int, float] = {}
    type_masteries: dict[int, float] = {}

    if skill_ids:
        for mastery in SkillMastery.objects.filter(user=user, skill_id__in=skill_ids):
            skill_masteries[mastery.skill_id] = _to_percent(mastery.mastery)

    if type_ids:
        for mastery in TypeMastery.objects.filter(user=user, task_type_id__in=type_ids):
            type_masteries[mastery.task_type_id] = _to_percent(mastery.mastery)

    return skill_masteries, type_masteries


def _get_self_paced_fallback(user, course: Course) -> float:
    try:
        enrollment = CourseEnrollment.objects.get(course=course, student=user)
    except CourseEnrollment.DoesNotExist:
        return 0.0
    return _to_percent(enrollment.progress)


def build_course_graph(user, course: Course) -> Dict[str, Any]:
    modules = list(
        CourseModule.objects.filter(course=course)
        .prefetch_related(
            Prefetch(
                "incoming_edges",
                queryset=CourseGraphEdge.objects.select_related("src").order_by("id"),
            ),
            Prefetch(
                "outgoing_edges",
                queryset=CourseGraphEdge.objects.select_related("dst").order_by("id"),
            ),
        )
        .order_by("rank", "col", "id")
    )

    if not modules:
        layout = None
    else:
        try:
            layout = course.layout
        except CourseLayout.DoesNotExist:
            layout = None

    skill_masteries, type_masteries = _load_mastery_maps(user, modules)
    fallback_mastery = _get_self_paced_fallback(user, course)

    edges: dict[int, SerializedEdge] = {}
    for module in modules:
        for edge in module.outgoing_edges.all():
            edges[edge.id] = SerializedEdge(
                id=edge.id,
                src=edge.src_id,
                dst=edge.dst_id,
                locked=edge.is_locked,
                kind=edge.kind,
                weight=float(edge.weight),
            )

    edge_states: dict[int, Dict[str, Any]] = {
        edge_id: asdict(edge) for edge_id, edge in edges.items()
    }

    module_masteries: dict[int, float] = {}
    for module in modules:
        if module.kind == CourseModule.Kind.SKILL and module.skill_id:
            mastery = skill_masteries.get(module.skill_id, 0.0)
        elif module.kind == CourseModule.Kind.TASK_TYPE and module.task_type_id:
            mastery = type_masteries.get(module.task_type_id, 0.0)
        else:
            mastery = fallback_mastery
        module_masteries[module.id] = mastery
        if mastery > 0.0:
            for edge in module.outgoing_edges.all():
                edge_states[edge.id]["locked"] = False

    serialized_nodes: list[SerializedNode] = []
    for module in modules:
        mastery = module_masteries.get(module.id, 0.0)
        incoming_edges = [edge.id for edge in module.incoming_edges.all()]
        outgoing_edges = [edge.id for edge in module.outgoing_edges.all()]
        incoming_unlocked = any(
            not edge_states[edge_id]["locked"] for edge_id in incoming_edges if edge_id in edge_states
        )
        locked = module.is_locked and mastery <= 0.0 and not incoming_unlocked
        serialized_nodes.append(
            SerializedNode(
                id=module.id,
                slug=module.slug,
                title=module.title,
                subtitle=module.subtitle,
                description=module.description,
                kind=module.kind,
                mastery=mastery,
                locked=locked,
                rank=module.rank,
                col=module.col,
                dx=module.dx,
                dy=module.dy,
                incoming=[edge_states[edge_id]["src"] for edge_id in incoming_edges if edge_id in edge_states],
                outgoing=[edge_states[edge_id]["dst"] for edge_id in outgoing_edges if edge_id in edge_states],
            )
        )

    layout_data: Dict[str, Any] | None = None
    if layout:
        layout_data = {
            "row_h": layout.row_h,
            "col_w": layout.col_w,
            "margin_x": layout.margin_x,
            "margin_y": layout.margin_y,
            "node_r": layout.node_r,
            "breakpoints": layout.breakpoints,
        }
        if layout.preset_name:
            layout_data["preset_name"] = layout.preset_name

    return {
        "layout": layout_data,
        "nodes": [asdict(node) for node in serialized_nodes],
        "edges": list(edge_states.values()),
    }
