#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def main():
    """Run administrative tasks."""
    root = Path(__file__).resolve().parent
    local_env = root / ".env.local"
    load_dotenv(dotenv_path=root / ".env")
    if local_env.is_file():
        load_dotenv(dotenv_path=local_env, override=True)
    default_settings = (
        "fractalschool.local_settings" if local_env.is_file() else "fractalschool.settings"
    )
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings)
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
