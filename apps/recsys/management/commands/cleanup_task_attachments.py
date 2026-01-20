from __future__ import annotations

from collections import deque
import posixpath

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand

from apps.recsys.models import TaskAttachment


def _iter_storage_files(prefix: str):
    queue = deque([prefix])
    seen = set()

    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)

        dirs, files = default_storage.listdir(current)
        for name in files:
            yield posixpath.join(current, name)
        for name in dirs:
            queue.append(posixpath.join(current, name))


class Command(BaseCommand):
    help = "Delete orphaned task attachment files from storage."

    def add_arguments(self, parser):
        parser.add_argument(
            "--prefix",
            default="tasks/",
            help="Storage prefix to scan (default: tasks/).",
        )
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Delete files instead of dry-run.",
        )

    def handle(self, *args, **options):
        prefix = options["prefix"] or ""
        delete_mode = bool(options["delete"])

        prefix = prefix.lstrip("/")
        if prefix and not prefix.endswith("/"):
            prefix = f"{prefix}/"

        existing_files = set(
            TaskAttachment.objects.exclude(file="").values_list("file", flat=True)
        )

        total = 0
        deleted = 0
        for storage_path in _iter_storage_files(prefix):
            total += 1
            if storage_path in existing_files:
                continue

            if delete_mode:
                default_storage.delete(storage_path)
                deleted += 1
            else:
                self.stdout.write(f"ORPHAN: {storage_path}")

        if delete_mode:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Removed {deleted} orphaned file(s) (scanned {total})."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry-run complete. {total} file(s) scanned. "
                    "Re-run with --delete to remove orphans."
                )
            )
