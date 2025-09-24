from django.contrib import admin

from .models import StudentProfile, TeacherProfile


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    search_fields = (
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
    )
    autocomplete_fields = ("exam_versions",)


@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    search_fields = (
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
    )
