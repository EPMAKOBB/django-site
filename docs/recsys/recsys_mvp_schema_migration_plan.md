# Recsys MVP Schema Migration Plan

This document maps the current Django schema to the canonical Recsys MVP schema.
Its purpose is to define the exact first migration wave before model code changes begin.

Related docs:
- [recsys_mvp_design_doc.md](./recsys_mvp_design_doc.md)
- [recsys_mvp_canonical_model.md](./recsys_mvp_canonical_model.md)

## 1. Scope

This plan covers:
- schema-level differences between the current codebase and the MVP model;
- what will be added in the first migration wave;
- what remains temporarily for compatibility;
- what is explicitly deferred.

This plan does not yet implement business logic, data backfill, or API rewrites.

## 2. Current State Summary

The current codebase already has:
- `TaskTag`
- `Task.tags`
- `TaskType`
- `Attempt`
- `TypeMastery`
- `RecommendationLog`
- `VariantTaskAttempt`

The major gaps relative to the MVP design are:
- no dedicated `TagMastery` model;
- `Task` lacks most automatic difficulty and control fields from the design;
- `Attempt` is still built around `is_correct`, `attempts_count`, and `weight`;
- `TypeMastery` is too thin and does not yet represent a full aggregate over tags;
- `RecommendationLog` is too thin and does not model recommendation lifecycle;
- `VariantTaskAttempt` lacks analytics validity markers.

## 3. Canonical Mapping

### 3.1. `Task`

Current model:
- already has `difficulty_level`, `first_attempt_total`, `first_attempt_failed`, `max_score`, `scoring_scheme`;
- currently stores `difficulty_level` as an integer-like field with `0..100` validation semantics.

Canonical MVP target:
- retain:
  - `exam_version`
  - `subject`
  - `type`
  - `max_score`
  - `scoring_scheme`
  - `first_attempt_total`
  - `first_attempt_failed`
- add:
  - `level_band`
  - `expected_time_seconds`
  - `difficulty_empirical`
  - `attempts_total`
  - `priority_manual`
  - `score_norm_sum_total`

Decision:
- `difficulty_level` remains on `Task`, but its semantic target is `0..1`.
- Because the current field type is `PositiveSmallIntegerField`, Wave 1 will not silently reinterpret it.
- Wave 1 should first add the missing fields and preserve compatibility.
- Wave 2 should convert `difficulty_level` to a float field and backfill values to the canonical `0..1` scale.

Reason:
- changing both field type and algorithmic semantics in the first migration would create avoidable risk.

### 3.2. `TagMastery`

Current model:
- missing.

Canonical MVP target:
- new table keyed by `(user_id, task_tag_id)` with:
  - `mastery`
  - `coverage`
  - `progress`
  - `confidence`
  - `stability`
  - `last_seen_at`
  - `last_success_at`
  - `attempts_total`
  - `successes_total`

Decision:
- introduce as a new model in Wave 1.
- do not try to reuse `SkillMastery`.

Reason:
- `TaskTag` already exists in schema and matches the design better than `Skill`.

### 3.3. `TypeMastery`

Current model:
- has only:
  - `user`
  - `task_type`
  - `mastery`
  - `confidence`

Canonical MVP target:
- keep existing identity fields;
- retain `mastery` and `confidence`;
- add:
  - `coverage`
  - `progress`
  - `stability`
  - `last_seen_at`
  - `last_success_at`
  - `attempts_total`
  - `successes_total`

Decision:
- extend the existing model in Wave 1.
- do not create a parallel type aggregate table.

### 3.4. `Attempt`

Current model:
- has:
  - `user`
  - `task`
  - `is_correct`
  - `attempts_count`
  - `variant_task_attempt`
  - `weight`

Canonical MVP target:
- retain:
  - `user`
  - `task`
  - `variant_task_attempt`
  - `is_correct`
- add:
  - `score`
  - `max_score`
  - `time_spent`
  - `is_valid_attempt`
  - `mode`
  - `checked_at`
  - `attempt_number`
  - `source_recommendation`

Compatibility status:
- `attempts_count` becomes legacy in Wave 1 and should still remain physically present for compatibility.
- `weight` becomes legacy in Wave 1 and should still remain physically present for compatibility.

Decision:
- add new fields in Wave 1;
- keep `attempts_count` and `weight` until service and API migration is complete;
- remove them only in a later cleanup migration.

### 3.5. `VariantTaskAttempt`

Current model:
- already has:
  - `attempt_number`
  - `is_correct`
  - `score`
  - `max_score`
  - `task_snapshot`
  - `time_spent`

Canonical MVP target:
- add:
  - `is_valid_attempt`
  - `checked_at`

Decision:
- Wave 1 adds these fields only.

### 3.6. `RecommendationLog`

Current model:
- has:
  - `user`
  - `task`
  - `completed`

Canonical MVP target:
- retain:
  - `user`
  - `task`
- add required lifecycle fields:
  - `status`
  - `recommended_at`
  - `source_mode`
  - `rank_position`
  - `attempt`
- optional snapshot fields:
  - `score_snapshot`
  - `reason_snapshot`
  - `weak_tags_snapshot`
  - `coverage_gain_snapshot`
  - `spacing_gain_snapshot`

Decision:
- Wave 1 adds:
  - `status`
  - `recommended_at`
  - `source_mode`
  - `rank_position`
  - `attempt`
- snapshot fields are deferred to Wave 2.
- `completed` remains temporarily as legacy compatibility.

Reason:
- lifecycle support is needed early;
- snapshot payloads are useful but not required to start implementation.

## 4. Migration Waves

## 4.1. Wave 1: Schema Foundation

Wave 1 is the first Django migration series and should include only low-risk schema additions plus one new model.

### `Task`

Add:
- `level_band`
- `expected_time_seconds`
- `difficulty_empirical`
- `attempts_total`
- `priority_manual`
- `score_norm_sum_total`

Recommended temporary defaults:
- `level_band = "exam"`
- `expected_time_seconds = NULL`
- `difficulty_empirical = 0.0`
- `attempts_total = 0`
- `priority_manual = 1.0`
- `score_norm_sum_total = 0.0`

### New `TagMastery`

Create model with:
- `user`
- `task_tag`
- `mastery`
- `coverage`
- `progress`
- `confidence`
- `stability`
- `last_seen_at`
- `last_success_at`
- `attempts_total`
- `successes_total`

And:
- unique constraint `(user, task_tag)`
- index `(user, task_tag)`

### `TypeMastery`

Add:
- `coverage`
- `progress`
- `stability`
- `last_seen_at`
- `last_success_at`
- `attempts_total`
- `successes_total`

Recommended defaults:
- numeric fields default to `0` / `0.0`
- timestamps nullable

### `Attempt`

Add:
- `score`
- `max_score`
- `time_spent`
- `is_valid_attempt`
- `mode`
- `checked_at`
- `attempt_number`
- `source_recommendation`

Recommended defaults:
- `score = NULL`
- `max_score = 1`
- `time_spent = NULL`
- `is_valid_attempt = True`
- `mode = "training"`
- `checked_at = NULL`
- `attempt_number = 1`
- `source_recommendation = NULL`

### `VariantTaskAttempt`

Add:
- `is_valid_attempt`
- `checked_at`

Recommended defaults:
- `is_valid_attempt = True`
- `checked_at = NULL`

### `RecommendationLog`

Add:
- `status`
- `recommended_at`
- `source_mode`
- `rank_position`
- `attempt`

Recommended defaults:
- `status = "recommended"`
- `recommended_at = created_at` for existing rows via data migration
- `source_mode = "unknown"` or `"training"` depending on final enum choice
- `rank_position = NULL`
- `attempt = NULL`

## 4.2. Wave 2: Semantic Alignment

Wave 2 should begin after the application reads and writes the new fields.

Includes:
- convert `Task.difficulty_level` to canonical float semantics in `0..1`;
- backfill `recommended_at`;
- optionally add recommendation snapshot fields;
- update admin, serializers, and services to rely on the new canonical fields;
- begin removing reads from legacy fields.

## 4.3. Wave 3: Cleanup

Remove deprecated fields after business logic and API migration is complete:
- `Attempt.attempts_count`
- `Attempt.weight`
- `RecommendationLog.completed`
- possibly `SkillMastery` if no remaining consumers exist

## 5. Required Enums and Value Sets

These values should be introduced centrally when model code is updated.

### `Task.level_band`

Values:
- `intro`
- `basic`
- `exam`
- `hard`

### `Attempt.mode`

Recommended MVP values:
- `training`
- `variant`

### `RecommendationLog.status`

Recommended MVP values:
- `recommended`
- `opened`
- `attempted`
- `completed`
- `dismissed`

### `RecommendationLog.source_mode`

Recommended MVP values:
- `training`
- `variant`
- `batch`
- `unknown`

## 6. Data Migration Rules for Existing Rows

Wave 1 should include lightweight, low-risk data backfill only.

### Existing `Task` rows

Set:
- `level_band = "exam"` if unknown;
- `priority_manual = 1.0`;
- `attempts_total = 0`;
- `score_norm_sum_total = 0.0`;
- `difficulty_empirical = 0.0`.

Do not attempt to derive accurate difficulty statistics in Wave 1.
That belongs to later recomputation logic.

### Existing `Attempt` rows

Set:
- `attempt_number = attempts_count` where present;
- `mode = "variant"` if `variant_task_attempt_id` is not null, otherwise `"training"`;
- `is_valid_attempt = True`;
- `max_score = 1` if unknown;
- `checked_at = created_at` as temporary fallback if needed.

### Existing `RecommendationLog` rows

Set:
- `recommended_at = created_at`;
- `status = "completed"` if legacy `completed=True`, else `status = "recommended"`.

## 7. Deliberately Deferred

The following items are explicitly out of scope for the first schema wave:
- recommendation snapshot payload fields;
- difficulty recalculation logic;
- forgetting and spacing batch logic;
- API contract migration;
- removal of `SkillMastery`;
- migration of current recommendation services;
- conversion of all tests to the new analytics model.

## 8. Completion Criteria

This migration-planning step is complete when:

1. The exact Wave 1 schema additions are fixed.
2. The legacy compatibility strategy is fixed.
3. A developer can update `apps/recsys/models.py` and generate migrations without reopening model-level design questions.
