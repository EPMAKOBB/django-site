from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Application
from .notifications import send_application_notification


@receiver(post_save, sender=Application)
def notify_application_created(sender, instance: Application, created: bool, **kwargs):
    if created:
        send_application_notification(instance)
