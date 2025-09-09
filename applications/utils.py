from __future__ import annotations

from datetime import date
from typing import TypedDict

# Pricing variants
VARIANT1_CURRENT = 3000
VARIANT1_ORIGINAL = 5000

VARIANT2_CURRENT = 5000
VARIANT2_ORIGINAL = 10000

PROMO_UNTIL = date(2025, 9, 30)


class ApplicationPrice(TypedDict):
    current: int
    original: int
    promo_until: date


def get_application_price(subjects_count: int) -> ApplicationPrice | None:
    """Return application price based on the number of subjects."""

    if subjects_count < 0:
        return None

    if subjects_count >= 2:
        current = VARIANT2_CURRENT
        original = VARIANT2_ORIGINAL
    else:
        current = VARIANT1_CURRENT
        original = VARIANT1_ORIGINAL

    return {
        "current": current,
        "original": original,
        "promo_until": PROMO_UNTIL,
    }
