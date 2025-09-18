from django.conf import settings
from django.db import models


class StudentProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    exam_versions = models.ManyToManyField(
        'recsys.ExamVersion', related_name='students', blank=True
    )

    def __str__(self):
        return f"{self.user.username} (student)"


class TeacherProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.username} (teacher)"
