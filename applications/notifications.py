import logging
import os
from typing import Iterable

import requests

from .models import Application

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("APPLICATION_BOT_API_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("CHAT1_ID")


def _or_placeholder(value: str | None) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else "—"


def _format_subjects(application: Application) -> str:
    subjects: Iterable[str] = application.subjects.values_list("name", flat=True)
    subjects_str = ", ".join(subjects)
    return subjects_str if subjects_str else "—"


def _lesson_type_label(lesson_type: str | None) -> str:
    lessons_map = {
        "group": "Group",
        "individual": "Individual",
        "pass": "Not specified",
    }
    if not lesson_type:
        return "—"
    return lessons_map.get(lesson_type, lesson_type)


def format_application_message(application: Application) -> str:
    grade = str(application.grade) if application.grade is not None else "—"
    lesson_type = _lesson_type_label(application.lesson_type)
    status = application.get_status_display()
    lines = [
        "Новая заявка",
        "",
        f"Contact name:\n{_or_placeholder(application.contact_name)}",
        "",
        f"Student name:\n{_or_placeholder(application.student_name)}",
        f"Grade:\n{grade}",
        "",
        f"Subjects:\n{_format_subjects(application)}",
        "",
        f"Contact info:\n{_or_placeholder(application.contact_info)}",
        "",
        f"Source offer:\n{_or_placeholder(application.source_offer)}",
        f"Lesson type:\n{lesson_type}",
        "",
        f"Status:\n{status}",
    ]
    return "\n".join(lines)


def send_application_notification(application: Application) -> None:
    """Send application data to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug(
            "Skipping Telegram notification: APPLICATION_BOT_API_TOKEN or CHAT1_ID missing"
        )
        return

    message = format_application_message(application)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}

    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code >= 400:
            logger.warning(
                "Telegram API returned %s: %s", response.status_code, response.text
            )
    except requests.RequestException:
        logger.exception("Failed to send Telegram application notification")
