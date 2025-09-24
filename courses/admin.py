from django.contrib import admin

from .models import Course, CourseEnrollment


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_active", "published_at", "created_at")
    list_filter = ("is_active", "level", "subject")
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("subject", "owner")


@admin.register(CourseEnrollment)
class CourseEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("course", "student", "status", "progress", "enrolled_at")
    list_filter = ("status", "course__subject")
    search_fields = (
        "course__title",
        "student__user__username",
        "student__user__email",
    )
    autocomplete_fields = ("course", "student")

