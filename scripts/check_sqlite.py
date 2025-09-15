import sqlite3
import sys
from pathlib import Path

db_path = Path(__file__).resolve().parents[1] / "db.sqlite3"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

print("Tables:")
for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
    print("-", name)

print("\napplications_application_subjects schema:")
for row in c.execute("PRAGMA table_info(applications_application_subjects)"):
    print(dict(row))

print("\nForeign keys for applications_application_subjects:")
for row in c.execute("PRAGMA foreign_key_list(applications_application_subjects)"):
    print(dict(row))

print("\nsubjects_subject rows:")
try:
    for row in c.execute("SELECT id, name, slug FROM subjects_subject"):
        print(dict(row))
except Exception as e:
    print("Error reading subjects_subject:", e)

print("\nExisting applications_subject rows:")
try:
    for row in c.execute("SELECT id, name, slug FROM applications_subject"):
        print(dict(row))
except Exception as e:
    print("Error reading applications_subject:", e)

print("\nApplied migrations:")
for row in c.execute("SELECT app, name FROM django_migrations ORDER BY app, name"):
    print(dict(row))

conn.close()
