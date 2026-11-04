from django.core.management.base import BaseCommand
from tutors.services import expire_bookings

class Command(BaseCommand):
    help = 'Освобождает просроченные запросы на запись'
    def handle(self, *args, **options):
        self.stdout.write(f'Просрочено записей: {expire_bookings()}')
