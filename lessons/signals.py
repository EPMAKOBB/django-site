from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Lesson, LessonEvent, LessonPayment


@receiver(post_save, sender=Lesson)
def initialize_lesson_records(sender, instance: Lesson, created: bool, **kwargs):
    if not created or kwargs.get("raw"):
        return
    LessonPayment.objects.get_or_create(
        lesson=instance,
        defaults={
            "amount": instance.price_amount,
            "currency": instance.currency,
        },
    )
    LessonEvent.objects.get_or_create(
        lesson=instance,
        event_type=LessonEvent.Type.CREATED,
        defaults={
            "actor": instance.created_by,
            "payload": {
                "scheduled_start": instance.scheduled_start.isoformat(),
                "duration_minutes": instance.duration_minutes,
                "price_amount": str(instance.price_amount),
                "currency": instance.currency,
            },
        },
    )
