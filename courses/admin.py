from django.contrib import admin

from .models import (
    Course,
    CourseEnrollment,
    CourseModule,
    CourseModuleItem,
    CourseTheoryCard,
)


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


class CourseModuleItemInline(admin.TabularInline):
    model = CourseModuleItem
    extra = 0
    autocomplete_fields = ("theory_card", "task")
    fields = (
        "position",
        "kind",
        "theory_card",
        "task",
        "min_mastery_percent",
        "max_mastery_percent",
    )
    ordering = ("position",)


@admin.register(CourseModule)
class CourseModuleAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "course",
        "kind",
        "rank",
        "col",
        "is_locked",
    )
    list_filter = ("course", "kind", "is_locked")
    search_fields = ("title", "slug", "course__title")
    prepopulated_fields = {"slug": ("title",)}
    inlines = (CourseModuleItemInline,)
    autocomplete_fields = ("course", "skill", "task_type")


@admin.register(CourseTheoryCard)
class CourseTheoryCardAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "difficulty_level")
    list_filter = ("course", "content_format")
    search_fields = ("title", "slug", "course__title")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("course",)
