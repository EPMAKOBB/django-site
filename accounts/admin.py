from django.contrib import admin

from .models import (
    StudentProfile,
    TeacherProfile,
    MethodistProfile,
    StudyClass,
    ClassStudentMembership,
    ClassTeacherSubject,
    TeacherStudentLink,
    TeacherSubjectInvite,
    ClassInvite,
    UserPreferences,
)


admin.site.register(StudentProfile)
admin.site.register(TeacherProfile)
admin.site.register(MethodistProfile)
admin.site.register(StudyClass)
admin.site.register(ClassStudentMembership)
admin.site.register(ClassTeacherSubject)
admin.site.register(TeacherSubjectInvite)
admin.site.register(ClassInvite)
admin.site.register(UserPreferences)


@admin.register(TeacherStudentLink)
class TeacherStudentLinkAdmin(admin.ModelAdmin):
    list_display = ("teacher", "student_record", "student", "subject", "status", "activated_at")
    list_filter = ("status", "subject")
    search_fields = (
        "teacher__username",
        "teacher__first_name",
        "teacher__last_name",
        "student__username",
        "student__first_name",
        "student__last_name",
        "student_record__full_name",
        "subject__name",
    )
    autocomplete_fields = ("teacher", "student_record", "student", "subject")
