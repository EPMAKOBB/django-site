"""Views for the students dashboard."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render

from .models import Assignment, Course, Submission


@login_required
def dashboard(request):
    """Display all courses with assignment completion progress."""

    if request.user.is_staff:
        return HttpResponseForbidden()

    courses = Course.objects.prefetch_related("assignments")
    submissions = Submission.objects.filter(student=request.user)
    submission_map = {sub.assignment_id: sub for sub in submissions}

    course_data = []
    for course in courses:
        assignments = list(course.assignments.all())
        completed = 0
        assignment_entries = []
        for assignment in assignments:
            submitted = assignment.id in submission_map
            if submitted:
                completed += 1
            assignment_entries.append(
                {"assignment": assignment, "submitted": submitted}
            )
        course_data.append(
            {
                "course": course,
                "assignments": assignment_entries,
                "completed": completed,
                "total": len(assignments),
            }
        )

    return render(request, "students/dashboard.html", {"course_data": course_data})

