from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render

from .models import Course, CourseGraphEdge, CourseModule, CourseModuleItem


@login_required
def module_detail(request, course_slug: str, module_slug: str):
    course = get_object_or_404(
        Course.objects.prefetch_related(
            Prefetch(
                "modules",
                queryset=CourseModule.objects.order_by("rank", "col", "id"),
            ),
            Prefetch(
                "graph_edges",
                queryset=CourseGraphEdge.objects.select_related("src", "dst"),
            ),
        ),
        slug=course_slug,
        is_active=True,
    )

    module = get_object_or_404(
        course.modules.prefetch_related(
            Prefetch(
                "items",
                queryset=CourseModuleItem.objects.select_related("theory_card", "task")
                .order_by("position", "id"),
            ),
        ),
        slug=module_slug,
    )

    incoming = [edge for edge in course.graph_edges.all() if edge.dst_id == module.id]
    outgoing = [edge for edge in course.graph_edges.all() if edge.src_id == module.id]

    context = {
        "course": course,
        "module": module,
        "items": list(module.items.all()),
        "incoming_edges": incoming,
        "outgoing_edges": outgoing,
    }
    return render(request, "courses/module_detail.html", context)
