from django.contrib import admin

from .models import StudentProfile, TeacherProfile


admin.site.register(StudentProfile)
admin.site.register(TeacherProfile)
