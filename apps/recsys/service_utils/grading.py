from __future__ import annotations

from typing import Any, Optional

from apps.recsys.forms import compare_answers
from apps.recsys.models import TaskType
from apps.recsys.answer_rules import digit_sequence, validate_digit_reference, paper_row_text


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

    if scoring_scheme in {TaskType.ScoringScheme.ORDERED_ONE_ERROR, TaskType.ScoringScheme.UNORDERED_TWO_PARTIAL}:
        validate_digit_reference(scoring_scheme, correct_answer, max_score)
        expected = digit_sequence(correct_answer)
        if scoring_scheme == TaskType.ScoringScheme.ORDERED_ONE_ERROR:
            actual = digit_sequence(response_value)
            if actual is None or len(actual) != len(expected):
                return 0, False
            errors = sum(a != b for a, b in zip(expected, actual))
            score = 2 if errors == 0 else (1 if errors == 1 else 0)
        else:
            # Extra slots are invalid even if normalization drops empty cells.
            raw = response_value.get("value") if isinstance(response_value, dict) else response_value
            if isinstance(raw, (list, tuple)) and len(raw) > 2 and paper_row_text(raw) is None:
                return 0, False
            actual = digit_sequence(response_value, allow_empty_cells=True)
            if actual is None or len(actual) > 2 or len(set(actual)) != len(actual):
                return 0, False
            score = len(set(expected) & set(actual))
        return score, score == 2

    if scoring_scheme in {TaskType.ScoringScheme.PARTIAL_PAIRS, TaskType.ScoringScheme.EGE_PAIRS_2027}:
        expected = _as_list(correct_answer)[:2]
        actual = _as_list(response_value)[:2]
        score = 0
        for idx in range(min(len(expected), len(actual))):
            try:
                if compare_answers(expected[idx], actual[idx]):
                    score += 1
            except Exception:
                continue
        if score == 0 and len(expected) == len(actual) == 2:
            try:
                if compare_answers(expected[0], actual[1]) and compare_answers(expected[1], actual[0]):
                    score = 1
            except Exception:
                pass
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
        if score == 0 and len(expected_rows) == len(actual_rows) == 2:
            try:
                if compare_answers(expected_rows[0], actual_rows[1]) and compare_answers(expected_rows[1], actual_rows[0]):
                    score = 1
            except Exception:
                pass
        score = min(score, max_score)
        return score, score == max_score

    # The 17-cell paper widget and scalar computer widgets share grading rules.
    expected_paper = paper_row_text(correct_answer)
    actual_paper = paper_row_text(response_value)
    if expected_paper is not None or actual_paper is not None:
        if expected_paper is not None:
            correct_answer = expected_paper
        if actual_paper is not None:
            response_value = actual_paper
        # Numeric paper answers may use a comma or a dot. Do not apply this to
        # computer arrays, pairs or matrices.
        import re
        from decimal import Decimal
        numeric = r'-?\d+(?:[.,]\d+)?'
        if re.fullmatch(numeric, str(correct_answer)) and re.fullmatch(numeric, str(response_value)):
            is_correct = Decimal(str(correct_answer).replace(',', '.')) == Decimal(str(response_value).replace(',', '.'))
            return (max_score if is_correct else 0), is_correct

    try:
        is_correct = compare_answers(
            _trim_trailing_blank_rows(correct_answer),
            _trim_trailing_blank_rows(response_value),
        )
    except Exception:
        is_correct = False
    return (max_score if is_correct else 0), bool(is_correct)
