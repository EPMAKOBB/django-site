from __future__ import annotations

from datetime import date
from typing import Optional, TypedDict

INDIVIDUAL_PRICE_PER_SUBJECT = 4000
GROUP_ORIGINAL_PRICE_PER_SUBJECT = 5000
GROUP_DISCOUNT_PRICE_PER_SUBJECT = 3000


class ApplicationPrice(TypedDict):
    current: int
    original: int | None
    promo_until: date | None


def get_application_price(
    lesson_type: str,
    subjects_count: int,
    *,
    with_discount: bool = False,
    promo_until: date | None = None,
) -> ApplicationPrice | None:
    """Calculate price details for the application.

    Returns ``None`` if ``lesson_type`` is unknown or ``subjects_count`` is not
    positive. Otherwise returns a dictionary with ``current`` price, optional
    ``original`` price and ``promo_until`` date when a discount applies.
    """
    if subjects_count <= 0:
        return None

    if lesson_type == "individual":
        current_per_subject = INDIVIDUAL_PRICE_PER_SUBJECT
        original_per_subject: int | None = None
    elif lesson_type == "group":
        if with_discount:
            current_per_subject = GROUP_DISCOUNT_PRICE_PER_SUBJECT
            original_per_subject = GROUP_ORIGINAL_PRICE_PER_SUBJECT
        else:
            current_per_subject = GROUP_ORIGINAL_PRICE_PER_SUBJECT
            original_per_subject = None
    else:
        return None

    current_total = current_per_subject * subjects_count
    original_total = (
        original_per_subject * subjects_count if original_per_subject else None
    )
    return {
        "current": current_total,
        "original": original_total,
        "promo_until": promo_until if original_total is not None else None,
    }
