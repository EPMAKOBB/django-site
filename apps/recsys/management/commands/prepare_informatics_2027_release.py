import json
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.recsys.models import ExamVersion
from apps.recsys.service_utils.release_2027 import prepare_release


class Command(BaseCommand):
    help = "Prepare informatics 2027 as a draft. Default: preview with rollback; never publishes."

    def add_arguments(self, parser):
        parser.add_argument("--source-exam-slug", required=True)
        parser.add_argument("--files", type=Path, required=True, help="Directory with the verified demo_23/24/27.txt files")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expect-database", help="Required for --apply; must equal the selected Django database NAME")
        parser.add_argument("--report", type=Path)

    def handle(self, *args, **options):
        if options["apply"] and options["expect_database"] != str(settings.DATABASES["default"]["NAME"]):
            raise CommandError("Для записи передайте --expect-database с точным именем выбранной базы.")
        try:
            source = ExamVersion.objects.get(slug=options["source_exam_slug"])
            result = prepare_release(source, files_dir=options["files"], apply=options["apply"])
        except (ValidationError, OSError, ExamVersion.DoesNotExist, ExamVersion.MultipleObjectsReturned) as exc:
            raise CommandError(str(exc)) from exc
        if options["report"]:
            options["report"].parent.mkdir(parents=True, exist_ok=True)
            options["report"].write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
