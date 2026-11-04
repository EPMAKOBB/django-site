"""Compact public summaries of the full teaching offers."""
from .models import Offering


def catalog_summary(offerings):
    subjects = {}
    for offering in offerings:
        group = subjects.setdefault(offering.subject_id, {
            'name': offering.subject.name,
            'goals': set(),
        })
        group['goals'].add(offering.goal)
    groups = [
        {'name': group['name'], 'goals': ', '.join(
            label for key, label in Offering.Goal.choices if key in group['goals']
        )}
        for group in subjects.values()
    ]
    result = {'subjects': groups, 'price': None, 'from_price': False, 'duration': None, 'price_note': ''}
    if not offerings:
        return result
    prices = [item.price for item in offerings]
    durations = {item.duration_minutes for item in offerings}
    if all(price is None for price in prices):
        result['price_note'] = 'Цена по договорённости'
    elif all(price is not None for price in prices) and len(durations) == 1:
        result.update(price=min(prices), from_price=len(set(prices)) > 1, duration=next(iter(durations)))
    return result
