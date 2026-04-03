# Recsys Scheduler Setup

## What Is Already Automatic

The project now refreshes student-side recsys state once per day on the first authenticated request.

This daily in-app refresh covers:
- tag forgetting decay;
- type mastery refresh from tags.

It does not replace the full server-side batch for global task difficulty updates.

---

## Recommended Schedule

For MVP:
- `students-only`: once per day;
- `tasks-only`: once per day.

Recommended commands:

```powershell
python manage.py recompute_recsys_state --students-only
python manage.py recompute_recsys_state --tasks-only
```

Or one combined run:

```powershell
python manage.py recompute_recsys_state
```

---

## Recommended Forgetting Parameters

Current implementation:

```text
delta_days = days since last_success_at
lambda_forget = lambda_forget_base / (1 + c_stability * stability)
mastery_new = mastery_old * exp(-lambda_forget * delta_days)
```

MVP coefficients:
- `lambda_forget_base = 0.03`
- `c_stability = 2.0`

Approximate half-life:
- `stability = 0.0` -> about `23` days
- `stability = 0.5` -> about `46` days
- `stability = 1.0` -> about `69` days

---

## Railway Scheduled Job

In Railway, add a scheduled job that runs:

```powershell
python manage.py recompute_recsys_state
```

Recommended cadence:
- daily at night or early morning UTC.

If you want to split load:
- one scheduled job for `--students-only`
- one scheduled job for `--tasks-only`

---

## Operational Note

If the external scheduler is temporarily disabled, the first authenticated request of the day still refreshes student-side state inside Django. That gives a safe fallback, but the preferred production setup is still a real scheduled job.
