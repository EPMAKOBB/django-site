from django.core.management.base import BaseCommand, CommandError
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

import os
from pathlib import Path
import uuid


class Command(BaseCommand):
    help = "Upload a local file to the configured DEFAULT_FILE_STORAGE (Yandex S3 if enabled) and print its public URL."

    def add_arguments(self, parser):
        parser.add_argument("--src", required=True, help="Path to a local file to upload")
        parser.add_argument(
            "--dst",
            default="uploads/",
            help="Destination prefix in storage (default: uploads/)",
        )
        parser.add_argument(
            "--name",
            default=None,
            help="Optional filename to use in storage (default: original name)",
        )

    def handle(self, *args, **options):
        src = options["src"]
        dst_prefix = options["dst"] or "uploads/"
        custom_name = options.get("name")

        src_path = Path(src)
        if not src_path.is_file():
            raise CommandError(f"Source file not found: {src}")

        # Build destination path
        original_name = custom_name or src_path.name
        dst_prefix = dst_prefix.strip("/")
        if dst_prefix:
            key_prefix = dst_prefix + "/"
        else:
            key_prefix = ""

        # Add a short UUID to avoid collisions when reusing names
        unique = uuid.uuid4().hex[:8]
        storage_name = f"{key_prefix}{unique}_{original_name}"

        # Read file and upload
        data = src_path.read_bytes()
        saved_name = default_storage.save(storage_name, ContentFile(data))
        url = default_storage.url(saved_name)

        self.stdout.write(self.style.SUCCESS(f"Uploaded: {saved_name}"))
        self.stdout.write(url)

