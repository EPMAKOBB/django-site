"""Safe settings for the self-contained local development environment."""

import os
from pathlib import Path

from dotenv import load_dotenv


_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env.local", override=True)
# manage.py loads the production-oriented .env first. Remove its database URLs
# before importing the base settings so local commands can never select them.
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_PUBLIC_URL", None)

from .settings import *  # noqa: E402,F403


DEBUG = True
SECRET_KEY = "local-development-only-do-not-use-in-production"

_host = os.environ.get("LOCAL_SITE_HOST", "127.0.0.1")
_site_port = os.environ.get("LOCAL_SITE_PORT", "8001")
if _host not in {"127.0.0.1", "localhost"}:
    raise RuntimeError("LOCAL_SITE_HOST must be localhost or 127.0.0.1")
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
CSRF_TRUSTED_ORIGINS = [
    f"http://127.0.0.1:{_site_port}",
    f"http://localhost:{_site_port}",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("LOCAL_DB_NAME", "fractalschool_local"),
        "USER": os.environ.get("LOCAL_DB_USER", "fractalschool_local"),
        "PASSWORD": "",
        "HOST": os.environ.get("LOCAL_DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("LOCAL_DB_PORT", "55438"),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"sslmode": "disable"},
    }
}

USE_S3_MEDIA = False
MEDIA_URL = "/media/"
MEDIA_ROOT = _ROOT / ".local" / "media"
STATIC_URL = "/static/"
STATIC_ROOT = _ROOT / ".local" / "static"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
SESSION_COOKIE_NAME = "fractalschool_local_sessionid"
CSRF_COOKIE_NAME = "fractalschool_local_csrftoken"
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}
