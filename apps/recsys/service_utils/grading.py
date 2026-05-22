from __future__ import annotations

from typing import Any, Optional

from apps.recsys.forms import compare_answers
from apps.recsys.models import TaskType


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value is None:
        return []
    return [value]


def _as_rows(value: Any) -> list[list[Any]]:
    rows = _as_list(value)
    normalized: list[list[Any]] = []
    for row in rows:
        if isinstance(row, list):
            normalized.append(row)
        elif isinstance(row, tuple):
            normalized.append(list(row))
        elif row is None:
            normalized.append([])
        else:
            normalized.append([row])
    return normalized


def _is_blank_row(row: Any) -> bool:
    if row in (None, ""):
        return True
    if isinstance(row, (list, tuple)):
        return all(cell in (None, "") for cell in row)
    return False


def _trim_trailing_blank_rows(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    if not all(isinstance(row, (list, tuple)) or row in (None, "") for row in value):
        return value
    rows = list(value)
    while rows and _is_blank_row(rows[-1]):
        rows.pop()
    return rows


def grade_answer(
    scoring_scheme: str,
    correct_answer: Any,
    response_value: Any,
    *,
    max_score: int,
) -> tuple[Optional[int], Optional[bool]]:
    if scoring_scheme == TaskType.ScoringScheme.MANUAL_SCALED:
        return None, None

    if scoring_scheme == TaskType.ScoringScheme.PARTIAL_PAIRS:
        expected = _as_list(correct_answer)[:2]
        actual = _as_list(response_value)[:2]
        score = 0
        for idx in range(min(len(expected), len(actual))):
            try:
                if compare_answers(expected[idx], actual[idx]):
                    score += 1
            except Exception:
                continue
        score = min(score, max_score)
        return score, score == max_score

    if scoring_scheme == TaskType.ScoringScheme.PARTIAL_ROWS:
        expected_rows = _as_rows(correct_answer)[:2]
        actual_rows = _as_rows(response_value)[:2]
        score = 0
        for idx in range(min(len(expected_rows), len(actual_rows))):
            exp_row = expected_rows[idx][:2]
            act_row = actual_rows[idx][:2]
            if len(act_row) < len(exp_row):
                continue
            row_ok = True
            for value_idx in range(len(exp_row)):
                try:
                    if not compare_answers(exp_row[value_idx], act_row[value_idx]):
                        row_ok = False
                        break
                except Exception:
                    row_ok = False
                    break
            if row_ok:
                score += 1
        score = min(score, max_score)
        return score, score == max_score

    try:
        is_correct = compare_answers(
            _trim_trailing_blank_rows(correct_answer),
            _trim_trailing_blank_rows(response_value),
        )
    except Exception:
        is_correct = False
    return (max_score if is_correct else 0), bool(is_correct)
