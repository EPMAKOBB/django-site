import os

from .settings import *  # noqa: F403


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("TEST_SQLITE_NAME", ":memory:"),
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# A legacy recsys migration contains PostgreSQL-only SQL. Unit tests use the
# current model state directly so they remain isolated and portable on SQLite.
MIGRATION_MODULES = {
    "accounts": None,
    "applications": None,
    "courses": None,
    "lessons": None,
    "parser_tasks": None,
    "recsys": None,
    "subjects": None,
    "students": None,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"], "level": "WARNING"},
}
