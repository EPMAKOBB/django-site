from __future__ import annotations

from datetime import date
from typing import TypedDict

# Pricing variant
VARIANT1_CURRENT = 3000
VARIANT1_ORIGINAL = 5000

PROMO_UNTIL = date(2025, 9, 30)


class ApplicationPrice(TypedDict):
    current: int
    original: int
    promo_until: date


def get_application_price(subjects_count: int) -> ApplicationPrice | None:
    """Return application price.

    Currently pricing does not depend on the number of subjects.
    """

    if subjects_count < 0:
        return None

    return {
        "current": VARIANT1_CURRENT,
        "original": VARIANT1_ORIGINAL,
        "promo_until": PROMO_UNTIL,
    }
