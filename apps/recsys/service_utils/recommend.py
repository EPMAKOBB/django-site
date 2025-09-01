"""Utilities for recommending tasks to users."""
from __future__ import annotations

import random
from datetime import timedelta
from typing import Iterable

from django.db.models import QuerySet

from apps.recsys.models import (
    Attempt,
    RecommendationLog,
    SkillMastery,
    Task,
    TaskSkill,
    TypeMastery,
)

__all__ = ["select_candidates", "score_task", "log_recommendations"]

# Exploration rate used by the ε-greedy strategy.
EPSILON = 0.1

# Relative weights of different factors in the score.
SKILL_WEIGHT = 0.7
TYPE_WEIGHT = 0.3


# ---------------------------------------------------------------------------
# Candidate selection and logging
# ---------------------------------------------------------------------------

def select_candidates(user, now) -> QuerySet[Task]:
    """Return tasks that may be recommended to ``user``.

    The implementation is deliberately straightforward: tasks already solved by
    the user as well as tasks that have been recommended within the last day are
    excluded from the result.
    """

    completed = Attempt.objects.filter(user=user, is_correct=True).values_list(
        "task_id", flat=True
    )
    recent_recs = RecommendationLog.objects.filter(
        user=user, created_at__gte=now - timedelta(days=1)
    ).values_list("task_id", flat=True)
    return Task.objects.exclude(id__in=completed).exclude(id__in=recent_recs)


def log_recommendations(user, tasks: Iterable[Task]) -> None:
    """Persist information about recommended ``tasks`` for ``user``."""

    logs = [RecommendationLog(user=user, task=task) for task in tasks]
    RecommendationLog.objects.bulk_create(logs, ignore_conflicts=True)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _skill_gap(user, task) -> float:
    """Return a value in [0, 1] describing how much the user lacks skills for the task."""

    skills = TaskSkill.objects.filter(task=task).select_related("skill")
    total_weight = 0.0
    score_sum = 0.0
    for ts in skills:
        mastery_obj = SkillMastery.objects.filter(user=user, skill=ts.skill).first()
        mastery = mastery_obj.mastery if mastery_obj else 0.0
        score_sum += (1.0 - mastery) * ts.weight
        total_weight += ts.weight
    if total_weight == 0:
        return 0.0
    return score_sum / total_weight


def _type_gap(user, task) -> float:
    tm = TypeMastery.objects.filter(user=user, task_type=task.type).first()
    mastery = tm.mastery if tm else 0.0
    return 1.0 - mastery


def score_task(user, task: Task, now) -> float:
    """Return a numerical score describing suitability of ``task`` for ``user``.

    The score combines the skill gap and the task type gap.  Exploration is
    implemented using an ε-greedy strategy: with probability ``EPSILON`` a random
    score is returned, encouraging exploration of new tasks.
    """

    if random.random() < EPSILON:
        # Exploration branch: score independent of mastery
        return random.random()

    skill_component = _skill_gap(user, task)
    type_component = _type_gap(user, task)
    return SKILL_WEIGHT * skill_component + TYPE_WEIGHT * type_component
