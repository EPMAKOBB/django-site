import os
import re
import psycopg2
from urllib.parse import urlparse

def load_env_db_url(path=".env"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("DATABASE_URL="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    return os.environ.get("DATABASE_URL")

db_url = load_env_db_url()
if not db_url:
    raise SystemExit("No DATABASE_URL found")

u = urlparse(db_url)
dbname = u.path.lstrip("/")
conn = psycopg2.connect(
    dbname=dbname,
    user=u.username,
    password=u.password,
    host=u.hostname,
    port=u.port or 5432,
    sslmode=(re.search(r"[?&]sslmode=(\w+)", db_url) or (None, "disable"))[1],
)
cur = conn.cursor()

print("Connected to:", dbname)

def table_exists(name):
    cur.execute(
        """
        select exists (
          select 1 from information_schema.tables
          where table_schema='public' and table_name=%s
        )
        """,
        (name,),
    )
    return cur.fetchone()[0]

for t in ["applications_application_subjects", "subjects_subject", "applications_subject"]:
    print(f"table {t} exists:", table_exists(t))

print("\nFKs referencing on applications_application_subjects:")
cur.execute(
    """
    select
      tc.constraint_name,
      kcu.column_name,
      ccu.table_name as foreign_table_name,
      ccu.column_name as foreign_column_name
    from
      information_schema.table_constraints as tc
      join information_schema.key_column_usage as kcu
        on tc.constraint_name = kcu.constraint_name
      join information_schema.constraint_column_usage as ccu
        on ccu.constraint_name = tc.constraint_name
    where tc.constraint_type = 'FOREIGN KEY'
      and tc.table_name='applications_application_subjects'
    order by kcu.column_name
    """
)
for row in cur.fetchall():
    print(row)

for t in ["subjects_subject", "applications_subject"]:
    if table_exists(t):
        cur.execute(f"select id, name, slug from {t} order by id limit 10")
        rows = cur.fetchall()
        print(f"\nRows in {t}:")
        for r in rows:
            print(r)

cur.close()
conn.close()
