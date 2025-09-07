from __future__ import annotations

from datetime import date
from typing import TypedDict

# Pricing variants
VARIANT1_CURRENT = 3000
VARIANT1_ORIGINAL = 5000
VARIANT2_CURRENT = 5000
VARIANT2_ORIGINAL = 10000
VARIANT3_PRICE = 2000

class ApplicationPrice(TypedDict):
    current: int
    original: int | None
    promo_until: date | None
    per_lesson: bool


def get_application_price(
    lesson_type: str,
    subjects_count: int,
    *,
    promo_until: date | None = None,
) -> ApplicationPrice | None:
    """Return application price based on lesson type and subjects count."""

    if subjects_count < 0:
        return None

    if subjects_count == 0:
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
            "current": VARIANT3_PRICE,
            "original": None,
            "promo_until": None,
            "per_lesson": True,
        }

    return {
        "current": VARIANT2_CURRENT,
        "original": VARIANT2_ORIGINAL,
        "promo_until": promo_until,
        "per_lesson": False,
    }
