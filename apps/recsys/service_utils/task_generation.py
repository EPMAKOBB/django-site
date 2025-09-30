"""Registry of task generators used to produce dynamic task content."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Callable, Dict, Iterable, Mapping, MutableMapping, Protocol, Sequence


if False:  # pragma: no cover - typing helpers
    from django.contrib.auth import get_user_model  # noqa: F401
    from apps.recsys.models import Task


@dataclass(slots=True)
class TaskGenerationResult:
    """Structured response returned by a task generator."""

    content: Mapping[str, object]
    answers: Mapping[str, object] | Sequence[object] | None = None
    payload: Mapping[str, object] | None = None
    meta: Mapping[str, object] | None = None


class TaskGenerator(Protocol):
    """Protocol describing a callable capable of generating a task."""

    def __call__(
        self,
        task: "Task",
        payload: MutableMapping[str, object],
        *,
        seed: int,
        student,
    ) -> TaskGenerationResult | Mapping[str, object]:
        ...


@dataclass(slots=True)
class _RegistryItem:
    slug: str
    generator: TaskGenerator
    label: str


_REGISTRY: Dict[str, _RegistryItem] = {}


def register_generator(slug: str, generator: TaskGenerator, *, label: str | None = None) -> None:
    """Register a new task generator under ``slug``."""

    if slug in _REGISTRY:
        raise ValueError(f"Генератор с ключом '{slug}' уже зарегистрирован")
    label = label or slug
    _REGISTRY[slug] = _RegistryItem(slug=slug, generator=generator, label=label)


def is_generator_registered(slug: str) -> bool:
    return slug in _REGISTRY


def get_generator(slug: str) -> TaskGenerator:
    try:
        return _REGISTRY[slug].generator
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(f"Генератор '{slug}' не найден") from exc


def get_generator_choices() -> Iterable[tuple[str, str]]:
    """Return tuples suitable for Django ``choices`` configuration."""

    return sorted(((item.slug, item.label) for item in _REGISTRY.values()), key=lambda x: x[1])


def generate(
    task: "Task",
    payload: MutableMapping[str, object],
    *,
    seed: int,
    student,
) -> TaskGenerationResult:
    """Execute the generator associated with ``task`` and normalise the result."""

    generator = get_generator(task.generator_slug)
    result = generator(task, payload, seed=seed, student=student)
    if isinstance(result, TaskGenerationResult):
        return result
    return TaskGenerationResult(content=result)


# ---------------------------------------------------------------------------
# Built-in generators


def _arithmetic_addition_generator(
    task: "Task",
    payload: MutableMapping[str, object],
    *,
    seed: int,
    student,
) -> TaskGenerationResult:
    """Produce a simple addition exercise."""

    rng = Random(seed)
    minimum = int(payload.get("min", 1))
    maximum = int(payload.get("max", 10))
    if minimum > maximum:
        minimum, maximum = maximum, minimum

    a = rng.randint(minimum, maximum)
    b = rng.randint(minimum, maximum)
    answer = a + b

    options = max(1, int(payload.get("options", 4)))
    choices = {answer}
    while len(choices) < options:
        delta = rng.randint(-5, 5) or rng.choice([-3, -2, 2, 3])
        choices.add(answer + delta)

    content = {
        "title": payload.get("title") or task.title,
        "question": f"{a} + {b}",
        "choices": sorted(choices),
        "rendering_strategy": task.rendering_strategy,
    }

    payload.update({"operands": [a, b], "options": options})

    return TaskGenerationResult(
        content=content,
        answers={"value": answer},
        payload=dict(payload),
        meta={"type": "arithmetic", "difficulty": payload.get("difficulty", "base")},
    )


def _word_sequence_generator(
    task: "Task",
    payload: MutableMapping[str, object],
    *,
    seed: int,
    student,
) -> TaskGenerationResult:
    """Produce a sequence completion task based on provided words."""

    words = list(payload.get("words", [])) or ["alpha", "beta", "gamma", "delta"]
    rng = Random(seed)
    rng.shuffle(words)
    hidden_index = rng.randrange(len(words))
    answer = words[hidden_index]

    content = {
        "title": payload.get("title") or task.title,
        "sequence": [w if i != hidden_index else "__" for i, w in enumerate(words)],
        "rendering_strategy": task.rendering_strategy,
    }

    return TaskGenerationResult(
        content=content,
        answers={"missing": answer},
        payload={"words": words, "hidden_index": hidden_index},
        meta={"type": "sequence"},
    )


register_generator(
    "math/addition",
    _arithmetic_addition_generator,
    label="Арифметика: сложение",
)
register_generator(
    "words/sequence",
    _word_sequence_generator,
    label="Продолжи последовательность",
)

from .generators.informatics import type23  # noqa: F401


__all__ = [
    "TaskGenerationResult",
    "generate",
    "get_generator",
    "get_generator_choices",
    "is_generator_registered",
    "register_generator",
]
