from django.contrib import admin

from .models import Course, CourseEnrollment


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "slug",
        "level",
        "language",
        "is_active",
        "enrollment_open",
        "published_at",
    )
    list_filter = ("level", "language", "is_active", "enrollment_open")
    search_fields = ("title", "slug", "short_description")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_at", "updated_at")


@admin.register(CourseEnrollment)
class CourseEnrollmentAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "course",
        "status",
        "enrolled_at",
        "progress",
        "grade",
    )
    list_filter = ("status", "course")
    search_fields = ("student__username", "course__title")
    autocomplete_fields = ("student", "course")
    readonly_fields = ("enrolled_at",)
