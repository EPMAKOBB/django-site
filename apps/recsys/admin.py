from django.contrib import admin

from .models import (
    Attempt,
    ExamVersion,
    RecommendationLog,
    Subject,
    Skill,
    SkillMastery,
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


admin.site.register(Skill)
admin.site.register(TaskType)
admin.site.register(TaskSkill)
admin.site.register(Attempt)
admin.site.register(SkillMastery)
admin.site.register(TypeMastery)
admin.site.register(RecommendationLog)
admin.site.register(Subject)
admin.site.register(ExamVersion)
