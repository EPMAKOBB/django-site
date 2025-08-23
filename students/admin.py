from django.contrib import admin

from .models import Assignment, Course, Submission


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title",)


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("title", "course")
    list_filter = ("course",)


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("assignment", "student", "submitted_at")
    list_filter = ("assignment", "student")
