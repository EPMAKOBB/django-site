import os
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fractalschool.settings")

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402


def main() -> None:
    prefixes_to_skip = (
        "django_",
        "auth_",
        "sqlite_",
        "admin_",
        "sessions",
    )

    with connection.cursor() as cur:
        all_tables = connection.introspection.table_names()
        tables = [t for t in all_tables if not t.startswith(prefixes_to_skip)]

        results = []
        for t in sorted(tables):
            # Count rows
            count = None
            try:
                cur.execute(f"SELECT COUNT(*) FROM \"{t}\"")
                count = cur.fetchone()[0]
            except Exception:
                count = None

            # Sample a few rows
            sample = []
            if (count or 0) > 0:
                try:
                    cur.execute(f"SELECT * FROM \"{t}\" LIMIT 3")
                    cols = [d[0] for d in cur.description]
                    for row in cur.fetchall():
                        sample.append(dict(zip(cols, row)))
                except Exception:
                    sample = []

            results.append({"table": t, "count": count, "sample": sample})

    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
