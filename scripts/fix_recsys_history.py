import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fractalschool.settings")
django.setup()
from django.db import connection
with connection.cursor() as c:
    c.execute("DELETE FROM django_migrations WHERE app=%s", ['recsys'])
print("✅ recsys history cleared")
