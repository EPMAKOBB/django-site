"""Files referenced by issued work must survive orphan cleanup."""
from urllib.parse import unquote, urlsplit
from html.parser import HTMLParser

from apps.recsys.models import Attempt, Task, TaskAttachment, TrainingSessionStep, VariantTaskAttempt, RecommendationLog


def referenced_storage_files():
    paths = set(TaskAttachment.objects.exclude(file="").values_list("file", flat=True))
    paths.update(Task.objects.exclude(image="").values_list("image", flat=True))

    class FileLinks(HTMLParser):
        def handle_starttag(self, tag, attrs):
            for name, value in attrs:
                if name in {"src", "href"} and value:
                    visit(value)

    def visit(value):
        if isinstance(value, dict):
            paths.update(value.get("storage_files", []))
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str):
            if "<" in value and ">" in value:
                FileLinks().feed(value)
                return
            # Legacy snapshots contain URLs instead of storage keys.
            try:
                path = unquote(urlsplit(value).path) if "\n" not in value and len(value) < 4096 else ""
            except ValueError:
                return
            if path.startswith("tasks/"):
                paths.add(path)
            elif "/tasks/" in path:
                paths.add("tasks/" + path.split("/tasks/", 1)[1])
    for model in (Attempt, TrainingSessionStep, VariantTaskAttempt, RecommendationLog):
        for snapshot in model.objects.values_list("task_snapshot", flat=True).iterator(chunk_size=1000):
            visit(snapshot)
    return paths
