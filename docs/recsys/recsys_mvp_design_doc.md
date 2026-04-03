# Recsys MVP Design Doc

## 1. System Goal

The recommendation system should not merely output tasks. It should guide the student toward the most effective exam preparation path.

Primary goals:
- improve the student's final result;
- close weak areas;
- ensure full coverage of required task types and tags;
- adapt task selection to the student's current level;
- minimize manual teacher involvement.

### Core Principle
Humans should define only what the system cannot reliably infer on its own:
- `level_band` — the pedagogical / exam-readiness level of the task;
- `priority_manual` — a manual task priority reflecting how close and useful the task is to the real exam.

Everything else should be inferred automatically from student attempt data whenever possible.

---

## 2. Overall Concept

The system is built around three layers:

### 2.1. Events

These are real user actions:
- opened a task;
- worked on a task;
- received a score;
- spent time;
- completed an attempt.

### 2.2. Student State

From events, the system builds the current student model:
- what the student knows;
- what the student does not know;
- what has already been covered;
- what is being forgotten;
- where the data is already reliable and where it is not.

### 2.3. Recommendations

Based on the student state, the system selects the next task or task set:
- useful for growth;
- useful for closing coverage gaps;
- aligned with the current level;
- important for the exam;
- appropriate in pace and difficulty.

---

## 3. Core Entities

## 3.1. `recsys_task`

Stores the properties of the task itself.

Role:
- defines the task structure;
- stores automatic aggregates for the task;
- stores manual control signals;
- provides data for the recommender to estimate difficulty and usefulness.

### What belongs to the task as an object

- subject;
- exam;
- task type;
- maximum score;
- scoring scheme;
- task level (`level_band`);
- expected time;
- manual priority;
- attempt aggregates;
- task difficulty.

---

## 3.2. `recsys_tagmastery`

The main student profile table at the tag level.

Role:
- stores current mastery for each tag;
- stores coverage;
- stores system confidence in the estimate;
- stores knowledge stability;
- acts as the main source for recommendations and weak-spot analysis.

This is the primary student analytics layer.

---

## 3.3. `recsys_typemastery`

Aggregated student state at the task-type level.

Role:
- shows state by exam number / task type;
- serves as a progress view by type;
- can be used as a cache of aggregates built on top of tags.

Types should be based on tags, not replace them.

---

## 3.4. `recsys_varianttaskattempt`

A task-solving attempt inside a mock exam / variant.

Role:
- stores the fact that the task was solved in the variant context;
- stores score, time, and attempt number;
- participates in student aggregate updates.

This is an event table.

---

## 3.5. `recsys_attempt`

A universal attempt table outside the variant context, primarily for training mode.

Role:
- stores training attempts;
- provides the basis for immediate adaptation after each task;
- allows training mode to evolve separately from variant mode.

This is an event table.

---

## 3.6. `recsys_recommendationlog`

Recommendation delivery log.

Role:
- stores what exactly was recommended;
- allows analysis of which recommendations were shown, opened, and solved;
- serves as the basis for recommender debugging and later improvement.

This is an event table.

---

## 4. Canonical Meaning of Terms

This section is mandatory. If these meanings are not fixed, the system will almost certainly drift semantically.

### `difficulty_level`

The current working task difficulty in the `0..1` range used by the recommender.

### `difficulty_empirical`

Raw statistical task difficulty calculated from valid student attempts.

### `level_band`

The pedagogical and exam-readiness level of the task.
This is not just difficulty, but the degree to which the task confirms readiness for the real exam.

### `priority_manual`

Manual task priority coefficient reflecting usefulness and similarity to the real exam.

### `mastery`

The current estimate of a student's proficiency in a tag or task type.
This is a working knowledge model that reacts to new attempts and forgetting.

### `coverage`

The degree to which required parts of preparation are actually covered.
`coverage` is not equal to `mastery`.

### `progress`

Visual progress for interface and gamification.
This is not the same as `mastery`.

### `confidence`

The system's confidence that its estimate is correct.

### `stability`

The degree to which knowledge is consolidated through successful confirmations at different points in time.

### `attempt_number`

The sequential number of a specific attempt for a task.

### `is_valid_attempt`

Flag indicating whether an attempt counts for analytics and recalculations.

---

## 5. The Role of `level_band`

`level_band` and difficulty are different concepts.

### Why this matters

- a task can be not very difficult but fully exam-representative;
- a task can be very easy but useful only as topic introduction;
- a task can be difficult without being central for confirming baseline exam readiness.

### `level_band` values

- `intro`
- `basic`
- `exam`
- `hard`

### Contribution coefficients for exam readiness

- `intro = 0.10`
- `basic = 0.30`
- `exam = 1.00`
- `hard = 1.30`

Meaning:
- `intro` — barely confirms exam readiness;
- `basic` — helps approach the topic;
- `exam` — full confirmation;
- `hard` — amplified confirmation.

These coefficients refer to readiness / contribution to exam readiness, not raw difficulty.

---

## 6. `recsys_task` Philosophy

For `recsys_task`, the following principle applies:

### Humans define only:

- `level_band`
- `priority_manual`

### The system calculates automatically:

- `attempts_total`
- `first_attempt_total`
- `first_attempt_failed`
- `difficulty_empirical`
- `difficulty_level`
- and, if needed, other statistical maturity aggregates.

### Why

The goal is to minimize manual work and make the system capable of learning from real student data.

---

## 7. Recommended Field Set for `recsys_task`

## 7.1. Already present and retained

- `exam_version_id`
- `subject_id`
- `type_id`
- `difficulty_level`
- `first_attempt_failed`
- `first_attempt_total`
- `max_score`
- `scoring_scheme`

## 7.2. Needs to be added

- `level_band`
- `expected_time_seconds`
- `difficulty_empirical`
- `attempts_total`
- `priority_manual`
- `score_norm_sum_total`

### Why `score_norm_sum_total` is needed

This is the sum of all `score / max_score` over valid attempts for a task.
It allows quick and simple updates of statistical difficulty without a heavy full-table recomputation.

---

## 8. Task Difficulty Strategy

## 8.1. New tasks

A new task must not require manual difficulty assessment by a teacher.

Initial difficulty should be set automatically through `level_band`.

### Recommended priors

- `intro -> 0.20`
- `basic -> 0.40`
- `exam -> 0.55`
- `hard -> 0.75`

These are starting difficulty priors, not readiness coefficients.

---

## 8.2. Empirical difficulty

Calculated from valid student attempts.

Formulas:

score_norm = score / max_score

score_norm_sum_total = score_norm_sum_total + score_norm

attempts_total = attempts_total + 1

success_empirical = score_norm_sum_total / attempts_total

difficulty_empirical = 1 - success_empirical

Bounds:
- `difficulty_empirical` from `0` to `1`

Meaning:
- the lower the average success, the higher the difficulty.

---

## 8.3. Working difficulty

Working difficulty is `difficulty_level`.

It should be smoothed so the task does not jump too sharply with a small number of attempts.

Formulas:

w_difficulty = attempts_total / (attempts_total + k_difficulty)

difficulty_level = w_difficulty * difficulty_empirical + (1 - w_difficulty) * difficulty_prior

where:
- `difficulty_prior` is set automatically from `level_band`;
- `k_difficulty` is the trust coefficient for statistics.

### Recommended `k_difficulty`

- minimum: `10`
- baseline: `30`
- maximum: `50`

Recommended value for MVP:
- `k_difficulty = 30`

---

## 8.4. Why `difficulty_final` is not needed

If we already have:
- `difficulty_empirical` — raw statistical difficulty;
- `difficulty_level` — working difficulty,

then a separate `difficulty_final` only creates a third concept for the same task and blurs meaning.

For MVP this is unnecessary.

---

## 9. First-Contact Statistics

`first_attempt_failed` and `first_attempt_total` should be kept.

They are not the primary difficulty signal, but they provide a separate and useful view:
how difficult the task is on first encounter.

### Meaning

- one task may be difficult at first contact but quickly learned;
- another may remain consistently difficult even after repetition.

This is useful additional analytics.

---

## 10. Attempt Formulas

After a valid attempt, base metrics are calculated first.

### Normalized score

score_norm = score / max_score

If max_score = 0, then score_norm = 0

### Time ratio

time_ratio = time_spent / expected_time_seconds

If `expected_time_seconds` is missing or equals 0, then `time_ratio = 1`

### Time coefficient

time_factor = exp(-lambda_time * max(0, min(time_ratio, 3.0) - 1))

Recommended `lambda_time`:
- minimum `0.2`
- baseline `0.5`
- maximum `1.0`

For MVP:
- `lambda_time = 0.5`

### Readiness band factor

readiness_band_factor:
- `intro = 0.10`
- `basic = 0.30`
- `exam = 1.00`
- `hard = 1.30`

### Base attempt quality

base_quality = score_norm * time_factor

### Final attempt quality for readiness

quality_score = base_quality * readiness_band_factor

---

## 11. `recsys_tagmastery`

Recommended field set:
- `id`
- `created_at`
- `updated_at`
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

### Constraints

- uniqueness `(user_id, task_tag_id)`
- index on `(user_id, task_tag_id)`

---

## 12. `recsys_typemastery`

Recommended field set:
- `id`
- `created_at`
- `updated_at`
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

### Constraints

- uniqueness `(user_id, task_type_id)`
- index on `(user_id, task_type_id)`

`recsys_typemastery` should act as a higher-level aggregate over tags.

---

## 13. `recsys_varianttaskattempt`

Already exists:
- `id`
- `created_at`
- `updated_at`
- `variant_attempt_id`
- `variant_task_id`
- `task_id`
- `attempt_number`
- `is_correct`
- `task_snapshot`
- `max_score`
- `score`
- `time_spent`

Needs to be added:
- `is_valid_attempt`
- `checked_at`

Role:
- store attempts in variant context;
- act as an event source for recalculating aggregates.

---

## 14. `recsys_attempt`

Already exists:
- `id`
- `created_at`
- `updated_at`
- `is_correct`
- `attempts_count`
- `user_id`
- `task_id`
- `variant_task_attempt_id`
- `weight`

Needs to be added:
- `score`
- `max_score`
- `time_spent`
- `is_valid_attempt`
- `mode`
- `checked_at`
- `attempt_number`
- `source_recommendation_id`

### Important rule

`attempts_count` and `attempt_number` must not coexist as different concepts.
One canonical meaning must be chosen.
The recommended canonical field is `attempt_number`.

---

## 15. `recsys_recommendationlog`

Already exists:
- `id`
- `created_at`
- `updated_at`
- `completed`
- `user_id`
- `task_id`

Needs to be added:
- `status`
- `recommended_at`
- `source_mode`
- `rank_position`
- `score_snapshot`
- `reason_snapshot`
- `weak_tags_snapshot`
- `coverage_gain_snapshot`
- `spacing_gain_snapshot`
- `attempt_id`

For MVP, some snapshot fields may be postponed if the first version should be lighter.

---

## 16. `recsys_tagmastery` Update Formulas

After each valid attempt, for all task tags:

### attempts_total

attempts_total_new = attempts_total_old + 1

### successes_total

success_flag = 1 if score_norm >= success_threshold

success_flag = 0 if score_norm < success_threshold

Recommended `success_threshold`:
- minimum `0.5`
- baseline `0.7`
- maximum `1.0`

For MVP:
- `success_threshold = 0.7`

successes_total_new = successes_total_old + success_flag

### mastery

mastery_new = (1 - alpha_mastery) * mastery_old + alpha_mastery * quality_score

Recommended `alpha_mastery`:
- minimum `0.05`
- baseline `0.15`
- maximum `0.3`

For MVP:
- `alpha_mastery = 0.15`

### coverage

coverage_gain = beta_coverage * quality_score

coverage_new = min(1.0, coverage_old + coverage_gain)

Recommended `beta_coverage`:
- minimum `0.03`
- baseline `0.08`
- maximum `0.2`

For MVP:
- `beta_coverage = 0.08`

### progress

progress_candidate = (1 - gamma_progress) * progress_old + gamma_progress * quality_score

progress_new = max(progress_old, progress_candidate)

Recommended `gamma_progress`:
- minimum `0.05`
- baseline `0.1`
- maximum `0.2`

For MVP:
- `gamma_progress = 0.1`

### confidence

confidence_new = 1 - exp(-attempts_total_new / k_confidence)

Recommended `k_confidence`:
- minimum `3`
- baseline `5`
- maximum `10`

For MVP:
- `k_confidence = 5`

### stability

If `success_flag = 1` and `last_success_at` was not today:

stability_new = min(1.0, stability_old + delta_stability)

Otherwise:

stability_new = stability_old

Recommended `delta_stability`:
- minimum `0.03`
- baseline `0.08`
- maximum `0.15`

For MVP:
- `delta_stability = 0.08`

### timestamps

last_seen_at = checked_at

If `success_flag = 1`:

last_success_at = checked_at

---

## 17. `recsys_typemastery` Update Formulas

After tag updates for the type:

mastery = avg(mastery_tag)
coverage = avg(coverage_tag)
progress = avg(progress_tag)
confidence = avg(confidence_tag)
stability = avg(stability_tag)

last_seen_at = max(last_seen_at_tag)
last_success_at = max(last_success_at_tag)

attempts_total = number of valid user attempts for tasks of this type
successes_total = number of successful valid user attempts for tasks of this type

---

## 18. Forgetting

Forgetting is better applied periodically:
- once a day;
- or when student analytics is opened.

### For mastery

delta_days = number of days since last_success_at

lambda_forget = lambda_forget_base / (1 + c_stability * stability)

mastery_decayed = mastery * exp(-lambda_forget * delta_days)

Recommended coefficients:
- `lambda_forget_base = 0.03`
- `c_stability = 2.0`

For MVP, decay may be applied only to `mastery`, while `coverage` and `progress` should not be reduced aggressively.

---

## 19. Weak Spots

For each tag:

forgetting_risk = 1 - exp(-mu_forgetting_risk * delta_days)

Recommended `mu_forgetting_risk`:
- minimum `0.02`
- baseline `0.05`
- maximum `0.1`

For MVP:
- `mu_forgetting_risk = 0.05`

### weakness_tag

weakness_tag = a_mastery * (1 - mastery) + a_coverage * (1 - coverage) + a_forgetting * forgetting_risk

Recommended coefficients:
- `a_mastery = 0.5`
- `a_coverage = 0.3`
- `a_forgetting = 0.2`

---

## 20. Recommendation Score

For each candidate task:

### task mastery

task_mastery = avg(mastery for task tags)

### predicted_success

predicted_success = 1 / (1 + exp(-eta_success * (task_mastery - difficulty_level)))

Recommended `eta_success`:
- minimum `3`
- baseline `5`
- maximum `8`

For MVP:
- `eta_success = 5`

### match_score

match_score = exp(-((predicted_success - target_success) ^ 2) / (2 * sigma_match ^ 2))

Recommended values:
- `target_success = 0.65`
- `sigma_match = 0.18`

### weak_gain

weak_gain = avg(weakness_tag for task tags)

### coverage_gain

coverage_gain = avg(1 - coverage for task tags)

### spacing_gain

spacing_gain = avg(forgetting_risk for task tags)

### data_bonus

data_bonus = 1 / (1 + attempts_total)

### final ranking

recommendation_score = priority_manual * (b_weak * weak_gain + b_coverage * coverage_gain + b_match * match_score + b_spacing * spacing_gain + b_data * data_bonus)

Recommended MVP coefficients:
- `b_weak = 0.35`
- `b_coverage = 0.25`
- `b_match = 0.25`
- `b_spacing = 0.10`
- `b_data = 0.05`

---

## 21. Recalculation Points

## 21.1. After one valid attempt

Recalculate:
- `score_norm`
- `time_ratio`
- `quality_score`
- `recsys_tagmastery`
- `recsys_typemastery`

If this is a training attempt, the next recommendation is built immediately afterward.

---

## 21.2. After mock exam completion

For all valid tasks in the variant:
- student aggregates are updated;
- weak spots are recalculated;
- recommendations are recalculated.

---

## 21.3. Periodic task batch

Once per day or after enough new attempts are accumulated:
- update `attempts_total`
- update `score_norm_sum_total`
- update `difficulty_empirical`
- update `difficulty_level`

---

## 21.4. Periodic student batch

Once per day or on login:
- apply forgetting;
- update spacing / repetition risks;
- recalculate recommendations if needed.

---

## 22. What Is Included in MVP

### Included in MVP

- `recsys_task` with automatic difficulty;
- `recsys_tagmastery`;
- `recsys_typemastery`;
- valid attempts;
- recalculation of mastery / coverage / confidence / stability;
- basic recommendation score;
- manual `level_band` and `priority_manual`.

### Can be postponed

- richer snapshot fields in recommendation log;
- more nuanced confidence models;
- extra aggregates such as average time per task;
- more advanced bandit mechanisms.

---

## 23. Main Project Decisions

1. `difficulty_level` is the working automatic task difficulty.
2. `difficulty_empirical` is the raw statistical difficulty.
3. `difficulty_final` is not needed.
4. `level_band` and difficulty are different concepts.
5. Humans define only `level_band` and `priority_manual`.
6. The system accumulates statistics and adjusts difficulty automatically.
7. `score_norm_sum_total` is required for simple and fast automatic task recalculation.
8. The main student analytics object is the tag, not the type.

---

## 24. One-Line Flow

Attempt -> normalized score and time -> tagmastery update -> typemastery aggregation -> task difficulty update -> recommendation recalculation
