from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

import requests
from bs4 import BeautifulSoup
from django.utils import timezone

from .models import ParserRun

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_URL = "https://inf-ege.sdamgia.ru/test?id=18833295"


class ParserServiceError(Exception):
    """Raised when fetching or parsing fails."""


@dataclass
class ParsedTask:
    number: int
    text: str
    answer: str | None


@dataclass
class ParserResult:
    source_url: str
    fetched_at: datetime
    tasks: list[ParsedTask]

    @property
    def tasks_count(self) -> int:
        return len(self.tasks)


def _iter_task_blocks(soup: BeautifulSoup) -> Sequence[BeautifulSoup]:
    selectors = [
        "div.problem",
        "div.task",  # fallback selector
    ]
    for selector in selectors:
        elements = soup.select(selector)
        if elements:
            return elements
    return []


def run_parser(source_url: str = DEFAULT_SOURCE_URL) -> ParserResult:
    """Fetch tasks from the provided URL and store the result snapshot."""

    logger.info("Starting parser run", extra={"source_url": source_url})
    try:
        response = requests.get(
            source_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; FractalParser/1.0)"},
            timeout=20,
        )
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - network failures
        logger.exception("Failed to fetch source", extra={"source_url": source_url})
        ParserRun.objects.create(
            source_url=source_url,
            status=ParserRun.Status.FAILURE,
            tasks_count=0,
            details=str(exc),
        )
        raise ParserServiceError("Не удалось получить данные для парсинга") from exc

    soup = BeautifulSoup(response.text, "html.parser")
    tasks: list[ParsedTask] = []

    for index, block in enumerate(_iter_task_blocks(soup), start=1):
        text_container = block.select_one(".problem_text") or block
        # Preserve the original HTML structure of the task description so that
        # SVGs and other markup are not stripped during parsing.
        text = text_container.decode_contents().strip()
        answer_node = block.select_one(".answer")
        answer: str | None = None
        if answer_node is not None:
            answer = answer_node.get_text(" ", strip=True)
        if text:
            tasks.append(ParsedTask(number=index, text=text, answer=answer))

    fetched_at = timezone.now()
    summary = f"Получено заданий: {len(tasks)}"
    ParserRun.objects.create(
        source_url=source_url,
        status=ParserRun.Status.SUCCESS,
        tasks_count=len(tasks),
        details=summary,
    )

    logger.info(
        "Parser run finished",
        extra={"source_url": source_url, "tasks_count": len(tasks)},
    )
    return ParserResult(source_url=source_url, fetched_at=fetched_at, tasks=tasks)
