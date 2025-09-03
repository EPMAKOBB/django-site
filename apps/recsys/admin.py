from django.contrib import admin

from .models import (
    Attempt,
    RecommendationLog,
    Skill,
    SkillMastery,
    Subject,
    Task,
    TaskSkill,
    TaskType,
    TypeMastery,
)


class TaskSkillInline(admin.TabularInline):
    model = TaskSkill
    extra = 1


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    inlines = [TaskSkillInline]
    list_display = ("title", "type")
    search_fields = ("title",)
    list_filter = ("type",)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ("name", "subject")
    search_fields = ("name",)
    list_filter = ("subject",)


@admin.register(TaskType)
class TaskTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "subject")
    search_fields = ("name",)
    list_filter = ("subject",)


admin.site.register(TaskSkill)
admin.site.register(Attempt)
admin.site.register(SkillMastery)
admin.site.register(TypeMastery)
admin.site.register(RecommendationLog)
