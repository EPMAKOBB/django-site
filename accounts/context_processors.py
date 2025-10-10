from __future__ import annotations

from typing import Any, Dict


SESSION_KEY = "variant_basket"


def _get_basket(request) -> dict:
    basket = request.session.get(SESSION_KEY) or {}
    tasks = basket.get("tasks") or []
    if not isinstance(tasks, list):
        tasks = []
    return {"tasks": tasks, "time_limit": basket.get("time_limit"), "deadline": basket.get("deadline")}


def variant_basket(request) -> Dict[str, Any]:
    """Expose variant basket info to all templates.

    Injects:
      - variant_basket_count: number of tasks in the basket
      - variant_basket_has_items: convenience boolean
    """
    try:
        basket = _get_basket(request)
        count = len(basket.get("tasks") or [])
    except Exception:
        count = 0
    return {
        "variant_basket_count": count,
        "variant_basket_has_items": bool(count),
    }

