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
)


admin.site.register(StudentProfile)
admin.site.register(TeacherProfile)
admin.site.register(MethodistProfile)
admin.site.register(StudyClass)
admin.site.register(ClassStudentMembership)
admin.site.register(ClassTeacherSubject)
admin.site.register(TeacherStudentLink)
admin.site.register(TeacherSubjectInvite)
admin.site.register(ClassInvite)
