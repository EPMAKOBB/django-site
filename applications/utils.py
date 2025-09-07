from __future__ import annotations

from typing import Dict, Optional

INDIVIDUAL_PRICE_PER_SUBJECT = 4000
GROUP_PRICE_PER_SUBJECT = 2500


def get_application_price(
    lesson_type: str, subjects_count: int
) -> Optional[Dict[str, str]]:
    """Return price details for the application.

    The price is calculated as a simple multiplication of the number of
    subjects by a predefined price per subject for each lesson type. If either
    ``subjects_count`` is non-positive or ``lesson_type`` is unknown, ``None``
    is returned.

    The dictionary contains the ``old`` price (20% higher), ``new`` price and
    a short ``note`` explaining the discount. Each value is formatted with a
    trailing ``"₽/мес"`` suffix.
    """
    if subjects_count <= 0:
        return None
    price_per_subject: Dict[str, int] = {
        "individual": INDIVIDUAL_PRICE_PER_SUBJECT,
        "group": GROUP_PRICE_PER_SUBJECT,
    }
    per_subject = price_per_subject.get(lesson_type)
    if per_subject is None:
        return None
    total = per_subject * subjects_count
    # Compute old price as 20% higher than current
    old_total = int(total * 1.2)
    # Format numbers with spaces as thousand separators
    total_str = f"{total:,}".replace(",", " ")
    old_str = f"{old_total:,}".replace(",", " ")
    return {
        "old": f"{old_str} ₽/мес",
        "new": f"{total_str} ₽/мес",
        "note": "скидка 20%",
    }
