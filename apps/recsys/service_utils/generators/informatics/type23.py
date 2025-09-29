from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from random import Random
from typing import Callable, Iterable, MutableMapping

from ...task_generation import TaskGenerationResult, register_generator


@dataclass(frozen=True, slots=True)
class _Command:
    """Description of an available instruction for the performer."""

    name: str
    description: str
    func: Callable[[int], int]

    def execute(self, value: int) -> int:
        return self.func(value)


def _choose_commands(rng: Random) -> list[_Command]:
    """Pick a deterministic yet diverse set of commands for the task."""

    commands: list[_Command] = []
    names: set[str] = set()
    target_count = rng.choice([2, 3])

    increments = [1, 2, 3, 4, 5, 6]
    multipliers = [2, 3]

    def add_command(cmd: _Command) -> None:
        if cmd.name not in names:
            commands.append(cmd)
            names.add(cmd.name)

    while len(commands) < target_count:
        remaining = target_count - len(commands)
        need_add = not any(cmd.name.startswith("прибавь") for cmd in commands)
        can_use_multiplier = bool(multipliers)

        choose_addition = need_add or remaining == 1 or not can_use_multiplier or rng.random() < 0.6

        if choose_addition:
            step = rng.choice(increments)
            add_command(
                _Command(
                    name=f"прибавь {step}",
                    description=f"Прибавляет к числу {step}",
                    func=lambda value, step=step: value + step,
                )
            )
        else:
            multiplier = rng.choice(multipliers)
            add_command(
                _Command(
                    name=f"умножь на {multiplier}",
                    description=f"Умножает число на {multiplier}",
                    func=lambda value, multiplier=multiplier: value * multiplier,
                )
            )

    return commands


def _build_reference_program(commands: Iterable[_Command]) -> list[dict[str, object]]:
    """Construct a structured description of the command list."""

    return [
        {
            "index": index + 1,
            "name": command.name,
            "description": command.description,
        }
        for index, command in enumerate(commands)
    ]


def _explore_tree(
    commands: Iterable[_Command],
    start: int,
    *,
    max_depth: int,
    limit_value: int,
) -> tuple[dict[int, list[dict[str, int]]], set[int], int, int]:
    """Traverse the state-space to estimate depth/width and transitions."""

    layers: list[set[int]] = [
        {start},
    ]
    transitions: dict[int, list[dict[str, int]]] = {}
    visited: set[int] = {start}

    for depth in range(max_depth):
        current = layers[depth]
        next_layer: set[int] = set()
        for value in current:
            available: list[dict[str, int]] = []
            for command in commands:
                next_value = command.execute(value)
                if next_value > limit_value or next_value == value:
                    continue
                available.append({"command": command.name, "result": next_value})
                if next_value not in visited:
                    visited.add(next_value)
                    next_layer.add(next_value)
            if available:
                transitions[value] = available
        if not next_layer:
            break
        layers.append(next_layer)

    depth_reached = len(layers) - 1
    max_width = max((len(layer) for layer in layers), default=1)
    return transitions, visited, depth_reached, max_width


def _count_paths(
    commands: list[_Command],
    start: int,
    target: int,
    max_depth: int,
    *,
    limit_value: int,
    required_mask: int = 0,
    forbidden_mask: int = 0,
) -> int:
    """Count valid command sequences under the provided constraints."""

    @lru_cache(maxsize=None)
    def visit(value: int, steps_left: int, used_mask: int) -> int:
        if value == target:
            return 1 if (used_mask & required_mask) == required_mask else 0
        if steps_left == 0:
            return 0

        total = 0
        for index, command in enumerate(commands):
            bit = 1 << index
            if forbidden_mask & bit:
                continue
            next_value = command.execute(value)
            if next_value > limit_value or next_value == value:
                continue
            total += visit(next_value, steps_left - 1, used_mask | bit)
        return total

    return visit(start, max_depth, 0)


def _pick_required(
    rng: Random,
    commands: list[_Command],
    start: int,
    target: int,
    max_depth: int,
    *,
    limit_value: int,
    base_count: int,
) -> tuple[int, int | None, int]:
    """Optionally pick a command that must appear in every valid program."""

    indices = list(range(len(commands)))
    rng.shuffle(indices)

    preferred: list[tuple[int, int, int]] = []
    fallback: list[tuple[int, int, int]] = []

    for index in indices:
        mask = 1 << index
        count = _count_paths(
            commands,
            start,
            target,
            max_depth,
            limit_value=limit_value,
            required_mask=mask,
        )
        if count > 0:
            record = (mask, index, count)
            fallback.append(record)
            if count < base_count:
                preferred.append(record)

    if preferred:
        return preferred[0]
    if fallback:
        return fallback[0]
    return 0, None, base_count


def _pick_forbidden(
    rng: Random,
    commands: list[_Command],
    start: int,
    target: int,
    max_depth: int,
    *,
    limit_value: int,
    required_mask: int,
    base_count: int,
) -> tuple[int, int | None, int]:
    """Optionally pick a command that cannot be used in valid programs."""

    indices = list(range(len(commands)))
    rng.shuffle(indices)

    candidates: list[tuple[int, int, int]] = []
    for index in indices:
        mask = 1 << index
        if required_mask & mask:
            continue
        count = _count_paths(
            commands,
            start,
            target,
            max_depth,
            limit_value=limit_value,
            required_mask=required_mask,
            forbidden_mask=mask,
        )
        if 0 < count < base_count:
            candidates.append((mask, index, count))

    if candidates:
        return candidates[0]
    return 0, None, base_count


def _make_content(
    task,
    reference_program: list[dict[str, object]],
    *,
    start: int,
    target: int,
    max_depth: int,
    commands: list[_Command],
    required_index: int | None,
    forbidden_index: int | None,
) -> dict[str, object]:
    """Prepare the content shown to a student."""

    command_lines = [
        f"{item['index']}. {item['name']} — {str(item['description']).lower()}."
        for item in reference_program
    ]

    title = getattr(task, "title", "Задание")

    conditions: list[str] = []
    if required_index is not None:
        conditions.append(
            f"Программа должна содержать хотя бы одну команду «{commands[required_index].name}»."
        )
    if forbidden_index is not None:
        conditions.append(
            f"Команда «{commands[forbidden_index].name}» использоваться не может."
        )

    question = (
        f"Сколько различных программ преобразуют число {start} в {target}, "
        f"используя не более {max_depth} команд?"
    )
    if conditions:
        question = question + " " + " ".join(conditions)

    statement = "\n".join(
        [
            "Исполнитель преобразует натуральное число, используя команды:",
            *command_lines,
            question,
        ]
    )

    return {
        "title": title,
        "statement": statement,
        "commands": reference_program,
        "start": start,
        "target": target,
        "max_steps": max_depth,
        "rendering_strategy": getattr(task, "rendering_strategy", None),
    }


def _make_payload(
    payload: MutableMapping[str, object],
    *,
    commands: list[_Command],
    start: int,
    target: int,
    max_depth: int,
    limit_value: int,
    transitions: dict[int, list[dict[str, int]]],
    required_index: int | None,
    forbidden_index: int | None,
) -> dict[str, object]:
    """Update and serialise payload for snapshot storage."""

    payload.update(
        {
            "start": start,
            "target": target,
            "max_depth": max_depth,
            "limit_value": limit_value,
            "commands": [
                {"name": command.name, "description": command.description}
                for command in commands
            ],
            "transitions": transitions,
            "required_command_index": required_index,
            "forbidden_command_index": forbidden_index,
        }
    )
    return dict(payload)


def _informatics_path_counter_generator(
    task,
    payload: MutableMapping[str, object],
    *,
    seed: int,
    student,
) -> TaskGenerationResult:
    """Generate an Informatics path-counter task."""

    rng = Random(seed)

    max_attempts = 50
    for _ in range(max_attempts):
        commands = _choose_commands(rng)
        start = int(payload.get("start") or rng.randint(2, 9))
        max_depth = int(payload.get("max_depth") or rng.randint(4, 7))
        target = int(payload.get("target") or rng.randint(start + 5, start + 60))
        limit_value = int(payload.get("limit_value") or max(target + rng.randint(3, 12), target + 5))

        reference_program = _build_reference_program(commands)
        transitions, visited, depth_reached, max_width = _explore_tree(
            commands,
            start,
            max_depth=max_depth,
            limit_value=limit_value,
        )

        if depth_reached == 0 or len(visited) > 120 or max_width > 40:
            continue

        total_paths = _count_paths(
            commands,
            start,
            target,
            max_depth,
            limit_value=limit_value,
        )
        if total_paths <= 0:
            continue

        required_mask, required_index, required_count = _pick_required(
            rng,
            commands,
            start,
            target,
            max_depth,
            limit_value=limit_value,
            base_count=total_paths,
        )
        if required_mask:
            total_paths = required_count

        forbidden_mask, forbidden_index, final_count = _pick_forbidden(
            rng,
            commands,
            start,
            target,
            max_depth,
            limit_value=limit_value,
            required_mask=required_mask,
            base_count=total_paths,
        )
        if forbidden_mask:
            total_paths = final_count

        final_paths = _count_paths(
            commands,
            start,
            target,
            max_depth,
            limit_value=limit_value,
            required_mask=required_mask,
            forbidden_mask=forbidden_mask,
        )
        if final_paths <= 0:
            continue

        content = _make_content(
            task,
            reference_program,
            start=start,
            target=target,
            max_depth=max_depth,
            commands=commands,
            required_index=required_index,
            forbidden_index=forbidden_index,
        )
        payload_snapshot = _make_payload(
            payload,
            commands=commands,
            start=start,
            target=target,
            max_depth=max_depth,
            limit_value=limit_value,
            transitions=transitions,
            required_index=required_index,
            forbidden_index=forbidden_index,
        )
        meta = {
            "type": "informatics",
            "subtype": "path-counter",
            "max_depth": max_depth,
            "state_count": len(visited),
            "depth_reached": depth_reached,
            "max_width": max_width,
        }
        answers = {"paths": final_paths}

        return TaskGenerationResult(
            content=content,
            answers=answers,
            payload=payload_snapshot,
            meta=meta,
        )

    raise RuntimeError("Не удалось сгенерировать корректное задание типа 23")


register_generator(
    "informatics/path-counter",
    _informatics_path_counter_generator,
    label="Информатика: подсчёт программ",
)


__all__ = ["_informatics_path_counter_generator"]
