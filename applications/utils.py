from __future__ import annotations

from datetime import date
from typing import TypedDict

# Pricing variants
VARIANT1_CURRENT = 3000
VARIANT1_ORIGINAL = 5000
VARIANT3_CURRENT = 2000
VARIANT3_ORIGINAL = 2500

INDIVIDUAL_ORIGINAL = 2500
INDIVIDUAL_CURRENT = 2000
INDIVIDUAL_PER_LESSON = True

class ApplicationPrice(TypedDict):
    current: int
    original: int
    promo_until: date
    per_lesson: bool


def get_application_price(
    lesson_type: str,
    subjects_count: int,
) -> ApplicationPrice | None:
    """Return application price based on lesson type and subjects count."""

    if subjects_count < 0:
        return None

    promo_until = date(date.today().year, 9, 30)

    if lesson_type == "individual":
        return {
            "current": INDIVIDUAL_CURRENT,
            "original": INDIVIDUAL_ORIGINAL,
            "promo_until": promo_until,
            "per_lesson": INDIVIDUAL_PER_LESSON,
        }

    if subjects_count <= 1:
        return {
            "current": VARIANT1_CURRENT,
            "original": VARIANT1_ORIGINAL,
            "promo_until": promo_until,
            "per_lesson": False,
        }

    if lesson_type not in {"individual", "group"}:
        return None

    if lesson_type == "group" and subjects_count == 2:
        return {
            "current": VARIANT3_CURRENT,
            "original": VARIANT3_ORIGINAL,
            "promo_until": promo_until,
            "per_lesson": True,
        }

    return None
