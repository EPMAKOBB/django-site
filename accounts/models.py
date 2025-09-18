from django.conf import settings
from django.db import models
from apps.recsys.models import ExamVersion


class StudentProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    exam_versions = models.ManyToManyField(
        ExamVersion,
        blank=True,
        related_name="students_preparing",
        help_text="Выбранные версии экзаменов, к которым готовится студент",
    )

    def __str__(self):
        return f"{self.user.username} (student)"


class TeacherProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)

    def __str__(self):
        return f"{self.user.username} (teacher)"
