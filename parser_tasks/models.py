from django.db import models


class ParserRun(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "success", "Успешно"
        FAILURE = "failure", "Ошибка"

    created_at = models.DateTimeField(auto_now_add=True)
    source_url = models.URLField()
    status = models.CharField(max_length=20, choices=Status.choices)
    tasks_count = models.PositiveIntegerField(default=0)
    details = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Запуск парсера"
        verbose_name_plural = "Запуски парсера"

    def __str__(self) -> str:  # pragma: no cover - human-readable representation
        return f"{self.get_status_display()} ({self.created_at:%Y-%m-%d %H:%M})"
