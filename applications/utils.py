from __future__ import annotations

from datetime import date
from typing import TypedDict

# Pricing variants
VARIANT1_CURRENT = 3000
VARIANT1_ORIGINAL = 5000
VARIANT2_CURRENT = 2000
VARIANT2_ORIGINAL = 2500
VARIANT3_CURRENT = 2000
VARIANT3_ORIGINAL = 2500

PROMO_UNTIL = date(2025, 9, 30)

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

    if lesson_type not in {"individual", "group"}:
        return None

    if lesson_type == "individual":
        return {
            "current": VARIANT2_CURRENT,
            "original": VARIANT2_ORIGINAL,
            "promo_until": PROMO_UNTIL,
            "per_lesson": True,
        }

    if subjects_count == 2:
        return {
            "current": VARIANT3_CURRENT,
            "original": VARIANT3_ORIGINAL,
            "promo_until": PROMO_UNTIL,
            "per_lesson": True,
        }

    return {
        "current": VARIANT1_CURRENT,
        "original": VARIANT1_ORIGINAL,
        "promo_until": PROMO_UNTIL,
        "per_lesson": False,
    }
