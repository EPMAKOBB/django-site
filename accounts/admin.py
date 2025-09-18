from django.contrib import admin

from .models import StudentProfile, TeacherProfile


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    filter_horizontal = ('exam_versions',)


admin.site.register(TeacherProfile)
