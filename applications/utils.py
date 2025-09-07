from __future__ import annotations

from typing import Dict

INDIVIDUAL_PRICE_PER_SUBJECT = 4000
GROUP_PRICE_PER_SUBJECT = 2500


def get_application_price(lesson_type: str, subjects_count: int) -> str:
    """Return price string for application depending on lesson type and subjects count.

    The price is calculated as a simple multiplication of the number of
    subjects by a predefined price per subject for each lesson type.
    The result is formatted with a trailing ``"₽/мес"`` suffix.
    """
    if subjects_count <= 0:
        return ""
    price_per_subject: Dict[str, int] = {
        "individual": INDIVIDUAL_PRICE_PER_SUBJECT,
        "group": GROUP_PRICE_PER_SUBJECT,
    }
    per_subject = price_per_subject.get(lesson_type)
    if per_subject is None:
        return ""
    total = per_subject * subjects_count
    # Format number with spaces as thousand separators
    total_str = f"{total:,}".replace(",", " ")
    return f"{total_str} ₽/мес"
