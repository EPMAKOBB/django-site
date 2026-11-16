"""Strict digit answers shared by reference validation and OGE grading."""
import re


def digit_sequence(value, *, allow_empty_cells=False):
    if isinstance(value, dict):
        if set(value) != {"value"}:
            return None
        value = value["value"]
    if isinstance(value, str):
        value = value.strip()
        return list(value) if re.fullmatch(r"[0-9]*", value) else None
    if type(value) is int:
        return list(str(value)) if value >= 0 else None
    if not isinstance(value, (list, tuple)):
        return None
    result = []
    for cell in value:
        if isinstance(cell, str):
            cell = cell.strip()
        if cell is None or cell == "":
            if allow_empty_cells:
                continue
            return None
        if type(cell) is int and 0 <= cell <= 9:
            result.append(str(cell))
        elif isinstance(cell, str) and re.fullmatch(r"[0-9]", cell):
            result.append(cell)
        else:
            return None
    return result


def validate_digit_reference(scheme, answer, max_score):
    if scheme not in {"ordered_one_error", "unordered_two_partial"}:
        return
    if max_score != 2:
        raise ValueError("Для этого правила максимальный балл должен быть равен 2.")
    expected = digit_sequence(answer)
    if not expected:
        raise ValueError("Эталон должен быть непустой последовательностью цифр.")
    if scheme == "unordered_two_partial" and (len(expected) != 2 or len(set(expected)) != 2):
        raise ValueError("Эталон выбора двух должен содержать ровно две разные цифры.")
