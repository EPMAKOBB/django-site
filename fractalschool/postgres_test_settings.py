"""Isolated integration tests with the complete PostgreSQL migration chain.

Uses a dedicated local server by default, never DATABASE_URL from .env.
"""
import os
from .test_settings import *  # noqa: F403

MIGRATION_MODULES = {}
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": os.environ.get("EXAM_TEST_DB", "exam_year_dev"),
    "USER": os.environ.get("EXAM_TEST_USER", "examdev"),
    "PASSWORD": os.environ.get("EXAM_TEST_PASSWORD", ""),
    "HOST": "127.0.0.1",
    "PORT": os.environ.get("EXAM_TEST_PORT", "55438"),
}}
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
