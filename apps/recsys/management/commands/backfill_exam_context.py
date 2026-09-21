import json
from pathlib import Path
from django.core.management.base import BaseCommand
from apps.recsys.service_utils.exam_history import backfill_context


class Command(BaseCommand):
    help = "Audit historical exam context; use --apply to fill it without replaying answers."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--report", help="Optional JSON report path")
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args, **options):
        result = backfill_context(apply=options["apply"], batch_size=max(1, options["batch_size"]))
        if options["report"]:
            Path(options["report"]).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(json.dumps({"apply": result["apply"], "counts": result["counts"], "issues": len(result["issues"])}, ensure_ascii=False))
