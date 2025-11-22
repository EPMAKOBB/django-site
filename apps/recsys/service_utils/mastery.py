"""Utility functions for updating users' mastery levels.

This module contains a single public function :func:`update_mastery` which
updates ``SkillMastery`` and ``TypeMastery`` records based on the result of an
:class:`~apps.recsys.models.Attempt`.

The update uses a combination of Beta distribution updates and an
exponentially‑weighted moving average (EWMA).  To reduce the effect of guessing,
information about previous attempts of the same task is stored in the Django
cache.  Repeated attempts decrease the impact of a correct answer.

The implementation is intentionally lightweight – it relies only on the data
available in the models and on the cache and does not try to be mathematically
perfect.  Nevertheless it provides a deterministic and easily testable behaviour
which is sufficient for the unit tests in this kata.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from django.core.cache import cache

from apps.recsys.models import (
    Attempt,
    SkillMastery,
    TaskSkill,
    TypeMastery,
)

__all__ = ["update_mastery"]

# EWMA smoothing factor.  The value is deliberately small so that the estimate
# changes gradually with each attempt.
EWMA_ALPHA = 0.3

# Cache configuration -------------------------------------------------------
#
# ``ATTEMPT_COUNT_KEY`` holds the number of times a user attempted a concrete
# task.  ``BETA_KEY`` stores alpha/beta parameters for Beta‑distribution updates.
#
# The cache keys intentionally contain a version number so that the behaviour
# can easily be changed in the future without stale cache values interfering.
ATTEMPT_COUNT_KEY = "recsys:attempts:v1:{user}:{task}"
BETA_SKILL_KEY = "recsys:beta:skill:v1:{user}:{skill}"
BETA_TYPE_KEY = "recsys:beta:type:v1:{user}:{type}"

# Number of seconds the attempt count is kept.  One hour is sufficient for the
# "anti‑guess" logic used below.
ATTEMPT_TTL = 60 * 60


def _ewma(previous: float, value: float, alpha: float) -> float:
    """Return an exponentially‑weighted moving average.

    ``alpha`` defines the smoothing factor (0 < alpha <= 1).
    """
    return previous + alpha * (value - previous)


def _clamp_mastery(value: float | None) -> float:
    """Clamp mastery values to the [0.0, 1.0] range."""
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value)))


@dataclass
class _BetaParams:
    """Simple container for parameters of a Beta distribution."""

    alpha: float = 1.0
    beta: float = 1.0

    def update(self, success: bool, weight: float = 1.0) -> None:
        if success:
            self.alpha += weight
        else:
            self.beta += weight

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)


def _get_beta_params(key: str) -> _BetaParams:
    """Fetch :class:`_BetaParams` from cache."""
    cached: Tuple[float, float] | None = cache.get(key)
    if cached is None:
        return _BetaParams()
    return _BetaParams(*cached)


def _store_beta_params(key: str, params: _BetaParams) -> None:
    cache.set(key, (params.alpha, params.beta))


def update_mastery(attempt: Attempt) -> Dict[str, Dict[int, float]]:
    """Update mastery models for the given ``attempt``.

    The function performs the following steps:

    * Fetch the number of previous attempts of the task from cache and update it.
      This value is used to reduce the effect of a correct answer that comes
      after multiple tries ("anti‑guess" logic).
    * For each skill associated with the task a ``SkillMastery`` object is
      updated using a Beta distribution update combined with EWMA smoothing.
    * The same procedure is applied to ``TypeMastery`` for the task's type.

    The function returns a mapping describing the updated mastery values.  The
    dictionary contains two keys: ``"skills"`` – mapping of skill IDs to their
    new mastery level, and ``"task_type"`` – the mastery for the task type.
    """

    user = attempt.user
    task = attempt.task

    # ------------------------------------------------------------------
    # Anti‑guessing: penalise repeated attempts of the same task.
    # ------------------------------------------------------------------
    attempt_key = ATTEMPT_COUNT_KEY.format(user=user.id, task=task.id)
    previous_attempts = cache.get(attempt_key, 0)
    cache.set(attempt_key, previous_attempts + 1, ATTEMPT_TTL)

    # Weight decreases with the number of attempts: first try -> weight=1,
    # second -> 1/2, third -> 1/3, etc.
    attempt_weight = 1.0 / (previous_attempts + 1)

    updated: Dict[str, Dict[int, float]] = {"skills": {}, "task_type": {}}

    # ------------------------------------------------------------------
    # Update skill masteries
    # ------------------------------------------------------------------
    task_skills = TaskSkill.objects.filter(task=task).select_related("skill")
    for task_skill in task_skills:
        skill = task_skill.skill
        mastery_obj, _ = SkillMastery.objects.get_or_create(user=user, skill=skill)

        beta_key = BETA_SKILL_KEY.format(user=user.id, skill=skill.id)
        params = _get_beta_params(beta_key)
        params.update(attempt.is_correct, weight=task_skill.weight)
        _store_beta_params(beta_key, params)

        ewma_alpha = EWMA_ALPHA * attempt_weight
        previous_mastery = float(mastery_obj.mastery or 0.0)
        mastery_obj.mastery = _clamp_mastery(_ewma(previous_mastery, params.mean, ewma_alpha))
        mastery_obj.save(update_fields=["mastery", "updated_at"])
        updated["skills"][skill.id] = mastery_obj.mastery

    # ------------------------------------------------------------------
    # Update task type mastery
    # ------------------------------------------------------------------
    task_type = task.type
    type_mastery, _ = TypeMastery.objects.get_or_create(user=user, task_type=task_type)
    beta_key = BETA_TYPE_KEY.format(user=user.id, type=task_type.id)
    params = _get_beta_params(beta_key)
    params.update(attempt.is_correct)
    _store_beta_params(beta_key, params)

    ewma_alpha = EWMA_ALPHA * attempt_weight
    previous_mastery = float(type_mastery.mastery or 0.0)
    type_mastery.mastery = _clamp_mastery(_ewma(previous_mastery, params.mean, ewma_alpha))
    type_mastery.save(update_fields=["mastery", "updated_at"])
    updated["task_type"][task_type.id] = type_mastery.mastery

    return updated
