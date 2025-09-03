from django.contrib import admin

from .models import (
    Attempt,
    ExamVersion,
    RecommendationLog,
    Skill,
    SkillMastery,
    Task,
    TaskSkill,
    TaskType,
    SkillGroup,
    SkillGroupItem,
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


class SkillGroupItemInline(admin.TabularInline):
    model = SkillGroupItem
    extra = 1


@admin.register(SkillGroup)
class SkillGroupAdmin(admin.ModelAdmin):
    inlines = [SkillGroupItemInline]
    list_display = ("title", "exam_version")
    list_filter = ("exam_version",)


class SkillGroupInline(admin.TabularInline):
    model = SkillGroup
    extra = 1


@admin.register(ExamVersion)
class ExamVersionAdmin(admin.ModelAdmin):
    inlines = [SkillGroupInline]
    list_display = ("name",)


admin.site.register(Skill)
admin.site.register(TaskType)
admin.site.register(TaskSkill)
admin.site.register(Attempt)
admin.site.register(SkillMastery)
admin.site.register(TypeMastery)
admin.site.register(RecommendationLog)
