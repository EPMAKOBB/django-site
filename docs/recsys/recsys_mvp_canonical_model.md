# Recsys MVP Canonical Model

This document fixes the canonical MVP model for implementation.
It does not replace the design doc. It translates it into a set of mandatory
technical decisions that migrations, services, and tests must follow.

## 1. Source of Truth

For MVP implementation, the source of truth is:

1. [recsys_mvp_design_doc.md](./recsys_mvp_design_doc.md) as the product and algorithm document.
2. This file as the technical definition of canonical entities and transition rules.

If the code diverges from this document, the code is considered legacy and must be migrated.

## 2. Canonical MVP Entities

### 2.1. `Task`

`Task` remains the canonical task entity.

Required manual fields:
- `level_band`
- `priority_manual`

Required automatic fields:
- `difficulty_empirical`
- `difficulty_level`
- `attempts_total`
- `score_norm_sum_total`
- `first_attempt_total`
- `first_attempt_failed`

Additional system field:
- `expected_time_seconds`

Canonical rules:
- `difficulty_level` is stored in the `0..1` range.
- `difficulty_empirical` is stored in the `0..1` range.
- the starting difficulty of a new task is defined by the prior from `level_band`.
- no separate `difficulty_final` field is introduced.

### 2.2. `TagMastery`

The main student analytics layer is built on `TaskTag`, not on `Skill`.

Canonical entity:
- `user_id`
- `task_tag_id`
- `mastery`
- `coverage`
- `progress`
- `confidence`
- `stability`
- `last_seen_at`
- `last_success_at`
- `attempts_total`
- `successes_total`

Canonical rules:
- uniqueness `(user_id, task_tag_id)`;
- all state fields are in the `0..1` range except counters and timestamps;
- updates are based only on valid attempts.

### 2.3. `TypeMastery`

`TypeMastery` remains, but its meaning changes:

- it is an aggregate over tags;
- it is a type-level progress view;
- it is not an independent primary knowledge layer.

Canonical fields:
- `user_id`
- `task_type_id`
- `mastery`
- `coverage`
- `progress`
- `confidence`
- `stability`
- `last_seen_at`
- `last_success_at`
- `attempts_total`
- `successes_total`

### 2.4. `Attempt`

`Attempt` is the canonical universal attempt event table.

Canonical fields:
- `user_id`
- `task_id`
- `variant_task_attempt_id`
- `source_recommendation_id`
- `mode`
- `attempt_number`
- `score`
- `max_score`
- `time_spent`
- `is_valid_attempt`
- `checked_at`
- `is_correct`

Canonical rules:
- `attempt_number` is the only canonical sequential attempt number;
- `attempts_count` is legacy and should be removed after the transition period;
- `is_correct` may remain as a derived or compatibility flag, but analytics must rely on `score`, `max_score`, and `is_valid_attempt`;
- training and variant flows differ by `mode`, not by separate analytics formulas.

### 2.5. `VariantTaskAttempt`

`VariantTaskAttempt` remains the event table for variant context.

Canonical MVP fields:
- `variant_attempt_id`
- `variant_task_id`
- `task_id`
- `attempt_number`
- `score`
- `max_score`
- `time_spent`
- `is_valid_attempt`
- `checked_at`
- `is_correct`
- `task_snapshot`

Canonical rules:
- it is the event source for variant mode;
- `Attempt` and `VariantTaskAttempt` must not drift semantically;
- if a variant attempt creates an `Attempt`, then `Attempt` is used for general student analytics.

### 2.6. `RecommendationLog`

`RecommendationLog` is the canonical log of recommendation delivery and outcome.

Canonical MVP fields:
- `user_id`
- `task_id`
- `recommended_at`
- `status`
- `source_mode`
- `rank_position`
- `attempt_id`

Optional first-wave fields:
- `score_snapshot`
- `reason_snapshot`
- `weak_tags_snapshot`
- `coverage_gain_snapshot`
- `spacing_gain_snapshot`

Canonical rules:
- `completed` is a legacy simplification;
- recommendation state is defined through `status`.

## 3. Canonical Analytics Layer

The following rules apply in MVP:

1. The main student analytics object is `TaskTag`.
2. The main event object is a valid attempt.
3. The main task aggregation object is `Task`.
4. The main recommendation object is a candidate task with computed `recommendation_score`.

Consequences:
- `SkillMastery` is not a canonical analytics layer for MVP.
- simply sorting tasks by average mastery is not a correct recommender anymore.
- `TypeMastery` must not be updated independently from the tag layer.

## 4. Canonical Ranges and Formats

### 4.1. Ranges

Fields in the `0..1` range:
- `difficulty_level`
- `difficulty_empirical`
- `mastery`
- `coverage`
- `progress`
- `confidence`
- `stability`
- `score_norm`
- `time_factor`
- `quality_score`
- `predicted_success`
- `match_score`
- `weakness_tag`
- `forgetting_risk`

### 4.2. Timestamps

- all analytics events use `checked_at` as the canonical event time;
- `created_at` does not replace `checked_at` if event time and row insertion time differ.

### 4.3. Attempt

Canonical minimal attempt payload for analytics:
- `user`
- `task`
- `score`
- `max_score`
- `time_spent`
- `checked_at`
- `is_valid_attempt`

If any of these fields is missing, the row may exist as a technical record but must not be treated as a full analytics event.

## 5. Transitional Legacy Layer

At the start of implementation, the codebase already contains simplified entities:
- `SkillMastery`
- `Attempt.attempts_count`
- `Attempt.weight`
- `RecommendationLog.completed`
- recommendation services built on `SkillMastery`

These are considered transitional legacy.

Transition rules:
- new services must not build new logic on top of `SkillMastery`;
- a short dual-write or read-compatibility period is acceptable;
- legacy fields are removed after API and test migration;
- new tests must be based on `TaskTag` / `TagMastery`, not on `SkillMastery`.

## 6. What Completes Step One

Step one is complete when:

1. The canonical model is fixed in documentation.
2. Each existing legacy entity has a defined status:
   - stays;
   - changes meaning;
   - is deprecated;
   - is removed later.
3. All following migrations and service changes are implemented against this model only.
