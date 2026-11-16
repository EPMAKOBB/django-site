"""Private, volume-backed storage; files are served only by authenticated views."""
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.files.storage import FileSystemStorage


def solution_storage():
    return FileSystemStorage(location=Path(settings.MEDIA_ROOT) / "_private_solutions")


def solution_photo_path(instance, filename):
    return f"{instance.solution_id}/{uuid4().hex}.jpg"
