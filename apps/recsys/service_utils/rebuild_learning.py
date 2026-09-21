"""Rebuild learning aggregates from events using the same rules as new answers."""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.recsys.models import Attempt, SkillMastery, TagMastery, TypeMastery
from apps.recsys.services import (
    _legacy_update_mastery, _quality_score, _update_tag_masteries, _update_type_mastery,
    apply_forgetting_to_tag_masteries, recompute_type_masteries_from_tags,
)


@transaction.atomic
def rebuild_learning_state(user, *, now=None):
    now = now or timezone.now()
    get_user_model().objects.select_for_update().get(pk=user.pk)
    events = list(Attempt.objects.filter(user=user, is_valid_attempt=True).select_related("task__type", "task_type").order_by("created_at", "pk"))
    events.sort(key=lambda event: (event.checked_at or event.created_at, event.pk))
    if events and (events[-1].checked_at or events[-1].created_at) > now:
        raise ValidationError("Момент пересчёта предшествует последнему ответу. Для истории используйте сохранённый снимок.")
    SkillMastery.objects.filter(user=user).update(mastery=0)
    shared = dict(mastery=0, coverage=0, progress=0, confidence=0, stability=0,
                  last_seen_at=None, last_success_at=None, attempts_total=0, successes_total=0)
    TagMastery.objects.filter(user=user).update(**shared, decayed_at=None)
    TypeMastery.objects.filter(user=user).update(**shared)
    for event in events:
        apply_forgetting_to_tag_masteries(now=event.checked_at or event.created_at, queryset=TagMastery.objects.filter(user=user))
        _legacy_update_mastery(event)
        quality, score = _quality_score(event)
        _update_tag_masteries(event, quality, score)
        _update_type_mastery(event)
    apply_forgetting_to_tag_masteries(now=now, queryset=TagMastery.objects.filter(user=user))
    recompute_type_masteries_from_tags(queryset=TypeMastery.objects.filter(user=user))
    return {"events": len(events), "algorithm": "event-learning-v1", "as_of": now.isoformat()}
