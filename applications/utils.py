from __future__ import annotations

from datetime import date
from typing import Dict, Optional

INDIVIDUAL_PRICE_PER_SUBJECT = 4000
GROUP_PRICE_PER_SUBJECT = 2500


def get_application_price(
    lesson_type: str,
    subjects_count: int,
    *,
    with_discount: bool = False,
    promo_until: Optional[date] = None,
) -> Optional[Dict[str, str]]:
    """Return price details for the application.

    The price is calculated as a simple multiplication of the number of
    subjects by a predefined price per subject for each lesson type. If either
    ``subjects_count`` is non-positive or ``lesson_type`` is unknown, ``None``
    is returned.

    When ``with_discount`` is ``True`` and ``promo_until`` is provided, the
    returned dictionary contains the ``original`` price (20% higher), ``current``
    price and a short ``note`` mentioning the validity date. Each value is
    formatted with a trailing ``"₽/мес"`` suffix. Otherwise only the ``current``
    price is included.
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
    # Format numbers with spaces as thousand separators
    total_str = f"{total:,}".replace(",", " ")
    result: Dict[str, str] = {"current": f"{total_str} ₽/мес"}
    if with_discount and promo_until:
        # Compute original price as 20% higher than current
        original_total = int(total * 1.2)
        original_str = f"{original_total:,}".replace(",", " ")
        result.update(
            {
                "original": f"{original_str} ₽/мес",
                "note": f"до {promo_until.strftime('%d.%m.%Y')}",
            }
        )
    return result
