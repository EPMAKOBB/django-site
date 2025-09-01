from django.apps import AppConfig


class RecsysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.recsys"

    def ready(self) -> None:  # pragma: no cover - side effects only
        from . import signals  # noqa: F401
