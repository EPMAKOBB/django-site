from django.db import models


class Subject(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)

    def __str__(self) -> str:  # type: ignore[override]
        return self.name


class Application(models.Model):
    class LessonType(models.TextChoices):
        INDIVIDUAL = "individual", "Individual"
        GROUP = "group", "Group"

    class Status(models.TextChoices):
        NEW = "new", "New"
        PROCESSED = "processed", "Processed"

    created_at = models.DateTimeField(auto_now_add=True)
    contact_name = models.CharField(max_length=255)
    student_name = models.CharField(max_length=255, null=True, blank=True)
    grade = models.PositiveSmallIntegerField()
    subjects = models.ManyToManyField(Subject, related_name="applications")
    contact_info = models.TextField()
    lesson_type = models.CharField(max_length=10, choices=LessonType)
    source_offer = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=Status, default=Status.NEW
    )

    def __str__(self) -> str:  # type: ignore[override]
        return f"Application from {self.contact_name}"
