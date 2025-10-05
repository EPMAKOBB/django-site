# fractalschool/settings.py
import os
import sys
from pathlib import Path
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-placeholder")
DEBUG = os.environ.get("DEBUG", "False") == "True"

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "")
ALLOWED_HOSTS = ALLOWED_HOSTS.split(",") if ALLOWED_HOSTS else []

CSRF_TRUSTED_ORIGINS = os.environ.get("CSRF_TRUSTED_ORIGINS", "")
CSRF_TRUSTED_ORIGINS = CSRF_TRUSTED_ORIGINS.split(",") if CSRF_TRUSTED_ORIGINS else []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "subjects",
    "accounts",
    "apps.recsys",
    "applications",
    "courses",
    "parser_tasks",
    # Storage backends (for S3/Yandex Object Storage)
    "storages",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "fractalschool.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "fractalschool.wsgi.application"

# Database: prefer DATABASE_URL, else DATABASE_PUBLIC_URL, else sqlite3
_db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PUBLIC_URL")

if _db_url:
    db_cfg = dj_database_url.parse(_db_url, conn_max_age=600, ssl_require=False)
    db_cfg["ENGINE"] = "django.db.backends.postgresql_psycopg2"
    host = (db_cfg.get("HOST") or "").lower()
    if host in ("localhost", "127.0.0.1"):
        db_cfg.setdefault("OPTIONS", {})["sslmode"] = "disable"
    else:
        db_cfg.setdefault("OPTIONS", {})["sslmode"] = "require"
    DATABASES = {"default": db_cfg}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
LOCALE_PATHS = [BASE_DIR / "locale"]

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "public" / "static"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "verbose": {
            "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",

            "formatter": "verbose",

        }
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "accounts": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        },
    },
}

# Media storage: use Yandex Object Storage (S3 compatible) when configured
#
# Required env vars when using Yandex Object Storage:
#   AWS_ACCESS_KEY_ID
#   AWS_SECRET_ACCESS_KEY
#   AWS_STORAGE_BUCKET_NAME
# Optional (with sensible defaults for Yandex):
#   AWS_S3_REGION_NAME (e.g., "ru-central1")
#   AWS_S3_ENDPOINT_URL (default: "https://storage.yandexcloud.net")
#   AWS_S3_CUSTOM_DOMAIN (e.g., "<bucket>.storage.yandexcloud.net")

_AWS_BUCKET = os.environ.get("AWS_STORAGE_BUCKET_NAME")
_if_s3 = bool(_AWS_BUCKET)

if _if_s3:
    # Endpoint/region defaults for Yandex Object Storage
    AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME", "ru-central1")
    AWS_S3_ENDPOINT_URL = os.environ.get(
        "AWS_S3_ENDPOINT_URL", "https://storage.yandexcloud.net"
    )
    AWS_S3_SIGNATURE_VERSION = os.environ.get("AWS_S3_SIGNATURE_VERSION", "s3v4")
    AWS_S3_ADDRESSING_STYLE = os.environ.get("AWS_S3_ADDRESSING_STYLE", "virtual")

    # Recommended settings (can override via AWS_DEFAULT_ACL env, e.g. "public-read")
    AWS_DEFAULT_ACL = os.environ.get("AWS_DEFAULT_ACL") or None
    AWS_S3_FILE_OVERWRITE = False
    AWS_QUERYSTRING_AUTH = os.environ.get("AWS_QUERYSTRING_AUTH", "False").lower() == "true"

    # Optional custom domain for cleaner URLs
    AWS_S3_CUSTOM_DOMAIN = os.environ.get(
        "AWS_S3_CUSTOM_DOMAIN", f"{_AWS_BUCKET}.storage.yandexcloud.net"
    )

    # Use S3Boto3 for media files
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

    # MEDIA_URL will be served via the S3 custom domain by default
    MEDIA_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/"
else:
    # Local media fallback (e.g., for development if bucket not configured)
    MEDIA_URL = "/media/"
    MEDIA_ROOT = BASE_DIR / "media"
