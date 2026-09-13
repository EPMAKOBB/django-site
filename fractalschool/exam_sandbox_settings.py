"""Local browser sandbox for reviewing annual exams, separate from test runners.

The database and uploaded files deliberately ignore production environment values.
See docs/recsys/exam_year_sandbox.md for the Windows setup instructions.
"""
from .settings import *  # noqa: F403

DEBUG = True
SECRET_KEY = "local-exam-sandbox-only-do-not-use-in-production"
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:8001", "http://localhost:8001"]

DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "exam_year_sandbox",
    "USER": "examdev",
    "PASSWORD": "",
    "HOST": "127.0.0.1",
    "PORT": "55438",
    "CONN_MAX_AGE": 0,
}}
MIGRATION_MODULES = {}

USE_S3_MEDIA = False
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / ".local" / "exam-sandbox" / "media"  # noqa: F405
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / ".local" / "exam-sandbox" / "static"  # noqa: F405
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
SESSION_COOKIE_NAME = "exam_sandbox_sessionid"
CSRF_COOKIE_NAME = "exam_sandbox_csrftoken"
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

# Keep ordinary password hashers so accounts in the restored copy can log in.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}
