from __future__ import annotations

from copy import deepcopy
from string import Formatter
from typing import Mapping
import os
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.text import slugify

from subjects.models import Subject
from apps.recsys.utils.sanitize import sanitize_html


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Skill(TimeStampedModel):
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="skills"
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("subject", "name")
        indexes = [models.Index(fields=["subject", "name"])]

    def __str__(self) -> str:
        return self.name


class TaskTag(TimeStampedModel):
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="task_tags"
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, blank=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("subject", "name")
        indexes = [models.Index(fields=["subject", "name"])]

    def __str__(self) -> str:
        return self.name


class Source(TimeStampedModel):
    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=150, unique=True, blank=True)
    exam_version = models.ForeignKey(
        "ExamVersion",
        on_delete=models.SET_NULL,
        related_name="sources",
        null=True,
        blank=True,
        help_text="Optional exam binding for this source.",
    )
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["slug"]),
            models.Index(fields=["exam_version", "name"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - human readable
        if self.exam_version_id:
            return f"{self.name} ({self.exam_version})"
        return self.name


class SourceVariant(TimeStampedModel):
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="variants")
    label = models.CharField(
        max_length=150,
        help_text="Например: дата варианта (13.12.2025) или номер (19).",
    )
    slug = models.SlugField(max_length=150, blank=True)

    class Meta:
        ordering = ["source__name", "label"]
        unique_together = ("source", "label")
        indexes = [
            models.Index(fields=["source", "label"]),
            models.Index(fields=["source", "slug"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - human readable
        return f"{self.source} — {self.label}"


class AnswerSchema(TimeStampedModel):
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Structure of answer fields (rows/columns, types, validation, optionality) "
            "used to render input UI and normalise answers."
        ),
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        unique_together = ("name",)
        indexes = [
            models.Index(
                fields=["name", "is_active"],
                name="recsys_answ_name_active",
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - human readable
        return self.name

    def clean(self):
        super().clean()
        if self.config is None:
            self.config = {}
        if not isinstance(self.config, dict):
            raise ValidationError({"config": "Answer schema config must be a JSON object."})


class TaskType(TimeStampedModel):
    class ScoringScheme(models.TextChoices):
        BINARY = "binary", "Binary (0/1)"
        PARTIAL_PAIRS = "partial_pairs", "Partial pairs (0-2)"
        PARTIAL_ROWS = "partial_rows", "Partial rows (0-2)"
        MANUAL_SCALED = "manual_scaled", "Manual scaled"

    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="task_types"
    )
    exam_version = models.ForeignKey(
        "ExamVersion",
        on_delete=models.CASCADE,
        related_name="task_types",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(
        max_length=128,
        null=True,
        blank=True,
        help_text="Machine-friendly code, e.g. algebra-basic",
    )
    description = models.TextField(blank=True)
    display_order = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Controls ordering of types within the same exam version. "
            "Lower numbers appear first."
        ),
    )
    required_tags = models.ManyToManyField(
        "TaskTag",
        blank=True,
        related_name="required_for_task_types",
    )
    answer_schema = models.ForeignKey(
        AnswerSchema,
        on_delete=models.SET_NULL,
        related_name="task_types",
        null=True,
        blank=True,
        help_text="How many answer inputs to show and of what kind (per subject/exam).",
    )
    scoring_scheme = models.CharField(
        max_length=32,
        choices=ScoringScheme.choices,
        default=ScoringScheme.BINARY,
        help_text="How to award points for answers of this task type.",
    )
    max_score = models.PositiveSmallIntegerField(
        default=1,
        help_text="Maximum primary points for this task type.",
    )

    class Meta:
        ordering = ["display_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["subject", "exam_version", "name"],
                name="task_type_subject_exam_name_unique",
            ),
            models.UniqueConstraint(
                fields=["subject", "exam_version", "slug"],
                name="task_type_subject_exam_slug_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["subject", "exam_version", "display_order", "name"]),
            models.Index(
                fields=["subject", "exam_version", "slug"],
                name="recsys_tt_subj_exam_slug_idx",
            ),
        ]

    def __str__(self) -> str:
        if self.exam_version:
            subject_name = self.exam_version.subject.name
            exam_name = self.exam_version.name
            return f"{subject_name} - {exam_name} - {self.name}"

        prefix = self.subject.name
        suffix = f"{self.name} (без версии экзамена)"
        return f"{prefix} · {suffix}"

    def _normalize_slug(self) -> None:
        raw_slug = self.slug or self.name
        slug_value = slugify(raw_slug or "")
        if slug_value:
            self.slug = slug_value

    def clean(self):
        super().clean()

        self._normalize_slug()
        if not self.slug:
            raise ValidationError({"slug": "Slug is required."})

        if self.exam_version and self.exam_version.subject_id != self.subject_id:
            raise ValidationError({"exam_version": "Exam version must match task subject."})

    def save(self, *args, **kwargs):
        self._normalize_slug()
        super().save(*args, **kwargs)

def _exam_version_slug(task: "Task") -> str:
    """
    Build a stable slug for exam version or subject, used in storage paths.
    Falls back to subject name/slug when exam_version is not set.
    """
    if task.exam_version:
        base = slugify(task.exam_version.name)
        if base:
            return base
        return f"exam-{task.exam_version_id or 'unknown'}"
    base = slugify(getattr(task.subject, "slug", None) or task.subject.name)
    return base or f"subject-{task.subject_id or 'unknown'}"


def task_image_upload_to(instance: "Task", filename: str) -> str:
    return f"tasks/bank/{instance.pk or 'new'}/{uuid4().hex}/images/{os.path.basename(filename)}"


def task_attachment_upload_to(instance: "TaskAttachment", filename: str) -> str:
    """New objects have unique keys under the stable task identity."""
    task = instance.task
    exam_slug = f"bank/{task.pk}/{uuid4().hex}"
    kind_folder = "images" if getattr(instance, "kind", "") == "image" else "files"

    # Allow explicit override for the stored filename (keeps prefix path only).
    if instance.download_name_override:
        override_name = os.path.basename(instance.download_name_override.strip())
        if override_name:
            override_root, override_ext = os.path.splitext(override_name)
            if not override_ext:
                _, original_ext = os.path.splitext(filename)
                override_name = f"{override_root}{original_ext.lower()}"
            return f"tasks/{exam_slug}/{kind_folder}/{override_name}"

    # Build base name
    base_slug = task.slug or slugify(task.title) or f"task-{task.pk or 'new'}"
    label_part = ""
    if instance.label:
        label_part = slugify(instance.label)
    elif instance.order and instance.order > 1:
        label_part = f"{instance.order:02d}"

    if label_part and label_part == base_slug:
        label_part = ""

    stem = f"{base_slug}-{label_part}" if label_part else base_slug
    root, ext = os.path.splitext(filename)
    safe_ext = ext.lower() if ext else ""
    final_name = f"{stem}{safe_ext}"
    return f"tasks/{exam_slug}/{kind_folder}/{final_name}"


def resolve_media_url(raw_url: str) -> str:
    """
    Return a browser-safe media URL.
    Some storages may return relative values like `tasks/...`; prepend MEDIA_URL.
    """
    if not raw_url:
        return ""
    lower = raw_url.lower()
    if raw_url.startswith("/") or lower.startswith("http://") or lower.startswith("https://"):
        return raw_url

    media_url = getattr(settings, "MEDIA_URL", "/media/") or "/media/"
    media_url = str(media_url).strip()
    if not media_url:
        media_url = "/media/"
    if not media_url.endswith("/"):
        media_url = media_url + "/"
    media_lower = media_url.lower()
    if not (media_url.startswith("/") or media_lower.startswith("http://") or media_lower.startswith("https://")):
        media_url = "/" + media_url
    return f"{media_url}{raw_url.lstrip('/')}"


class Task(TimeStampedModel):
    class LevelBand(models.TextChoices):
        INTRO = "intro", "Intro"
        BASIC = "basic", "Basic"
        EXAM = "exam", "Exam"
        HARD = "hard", "Hard"

    slug = models.SlugField(
        max_length=128,
        unique=True,
        null=True,
        blank=True,
        help_text="Machine-friendly code, e.g. 17-01-krylov",
    )
    scoring_scheme = models.CharField(
        max_length=32,
        choices=TaskType.ScoringScheme.choices,
        null=True,
        blank=True,
        help_text="Optional override of task-type scoring scheme.",
    )
    answer_schema = models.ForeignKey(
        AnswerSchema,
        on_delete=models.SET_NULL,
        related_name="tasks",
        null=True,
        blank=True,
        help_text="Optional override of task-type answer schema (fields per answer).",
    )
    max_score = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Optional override of task-type max score.",
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="tasks"
    )
    source = models.ForeignKey(
        Source,
        on_delete=models.SET_NULL,
        related_name="tasks",
        null=True,
        blank=True,
    )
    source_variant = models.ForeignKey(
        SourceVariant,
        on_delete=models.SET_NULL,
        related_name="tasks",
        null=True,
        blank=True,
    )
    exam_version = models.ForeignKey(
        "ExamVersion",
        on_delete=models.CASCADE,
        related_name="tasks",
        null=True,
        blank=True,
    )
    type = models.ForeignKey(TaskType, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    skills = models.ManyToManyField("Skill", through="TaskSkill", related_name="tasks")
    tags = models.ManyToManyField(
        "TaskTag",
        blank=True,
        related_name="tasks",
    )
    is_dynamic = models.BooleanField(default=False)

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        REVIEW = "review", "Review"
        CHANGES_REQUESTED = "changes_requested", "Changes requested"
        APPROVED = "approved", "Approved"
        SCHEDULED = "scheduled", "Scheduled"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"
        REJECTED = "rejected", "Rejected"

    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
    )

    class DynamicMode(models.TextChoices):
        GENERATOR = "generator", "Generator"
        PRE_GENERATED = "pre_generated", "Pre-generated pool"

    generator_slug = models.CharField(max_length=255, blank=True)
    dynamic_mode = models.CharField(
        max_length=32,
        choices=DynamicMode.choices,
        default=DynamicMode.GENERATOR,
    )
    default_payload = models.JSONField(default=dict, blank=True)
    image = models.ImageField(upload_to=task_image_upload_to, blank=True)
    correct_answer = models.JSONField(blank=True, default=dict)
    level_band = models.CharField(
        max_length=16,
        choices=LevelBand.choices,
        default=LevelBand.EXAM,
    )
    expected_time_seconds = models.PositiveIntegerField(null=True, blank=True)
    difficulty_empirical = models.FloatField(default=0.0)
    difficulty_level = models.PositiveSmallIntegerField(default=0)
    attempts_total = models.PositiveIntegerField(default=0)
    priority_manual = models.FloatField(default=1.0)
    score_norm_sum_total = models.FloatField(default=0.0)
    time_spent_sum_seconds = models.FloatField(default=0.0)
    time_spent_count = models.PositiveIntegerField(default=0)
    time_spent_avg_seconds = models.FloatField(null=True, blank=True)
    first_attempt_total = models.PositiveIntegerField(default=0)
    first_attempt_failed = models.PositiveIntegerField(default=0)

    class RenderingStrategy(models.TextChoices):
        PLAIN = "plain", "Plain text"
        MARKDOWN = "markdown", "Markdown"
        HTML = "html", "HTML"

    rendering_strategy = models.CharField(
        max_length=32,
        choices=RenderingStrategy.choices,
        default=RenderingStrategy.MARKDOWN,
    )

    class Meta:
        unique_together = ("subject", "exam_version", "type", "title")
        indexes = [
            models.Index(fields=["subject", "exam_version", "type", "title"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return self.title

    def clean(self):
        super().clean()

        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values("type_id", "exam_version_id").first()
            if previous and (previous["type_id"], previous["exam_version_id"]) != (self.type_id, self.exam_version_id) and self.placements.exists():
                raise ValidationError("Исходная классификация общей задачи сохраняется. Для другого года добавьте назначение.")

        raw_slug = self.slug or self.title
        self.slug = slugify(raw_slug or "") or self.slug
        if not self.slug:
            raise ValidationError({"slug": "Slug is required."})

        if self.type and self.type.subject_id != self.subject_id:
            raise ValidationError({"type": "Task type must match task subject."})
        if self.exam_version and self.exam_version.subject_id != self.subject_id:
            raise ValidationError({"exam_version": "Exam version must match task subject."})
        if self.source_variant and self.source and self.source_variant.source_id != self.source_id:
            raise ValidationError({"source_variant": "Вариант источника должен совпадать с источником."})
        if self.source_variant and not self.source:
            self.source = self.source_variant.source

        payload = self.default_payload or {}
        if not isinstance(payload, dict):
            raise ValidationError(
                {"default_payload": "Payload должен быть объектом JSON"}
            )
        # Normalise JSON field to avoid shared mutable defaults
        self.default_payload = deepcopy(payload)

        answer = self.correct_answer if self.correct_answer not in (None, "") else {}
        schema = None
        try:
            schema = self.get_answer_schema()
        except Exception:
            schema = None

        if schema is None:
            if not isinstance(answer, dict):
                raise ValidationError(
                    {"correct_answer": "Правильный ответ должен быть объектом JSON"}
                )
        self.correct_answer = deepcopy(answer)

        if not 0 <= self.difficulty_level <= 100:
            raise ValidationError(
                {"difficulty_level": "Сложность должна быть в диапазоне 0–100"}
            )
        if not 0.0 <= float(self.difficulty_empirical or 0.0) <= 1.0:
            raise ValidationError(
                {"difficulty_empirical": "Empirical difficulty must be in the 0..1 range."}
            )
        if self.priority_manual is not None and float(self.priority_manual) < 0.0:
            raise ValidationError(
                {"priority_manual": "Manual priority must be non-negative."}
            )
        if self.expected_time_seconds is not None and self.expected_time_seconds <= 0:
            raise ValidationError(
                {"expected_time_seconds": "Expected time must be positive."}
            )
        if self.attempts_total < 0:
            raise ValidationError({"attempts_total": "Attempts total must be non-negative."})
        if float(self.score_norm_sum_total or 0.0) < 0.0:
            raise ValidationError(
                {"score_norm_sum_total": "Score norm sum total must be non-negative."}
            )
        if float(self.time_spent_sum_seconds or 0.0) < 0.0:
            raise ValidationError(
                {"time_spent_sum_seconds": "Time spent sum must be non-negative."}
            )
        if self.time_spent_count < 0:
            raise ValidationError({"time_spent_count": "Time spent count must be non-negative."})
        if self.time_spent_avg_seconds is not None and float(self.time_spent_avg_seconds) < 0.0:
            raise ValidationError(
                {"time_spent_avg_seconds": "Average time spent must be non-negative."}
            )

        if self.max_score is not None and self.max_score <= 0:
            raise ValidationError({"max_score": "Max score must be positive."})

        mode = self.dynamic_mode or self.DynamicMode.GENERATOR

        if self.is_dynamic:
            if mode == self.DynamicMode.GENERATOR:
                if not self.generator_slug:
                    raise ValidationError(
                        {"generator_slug": "Для динамических задач требуется генератор"}
                    )
                from apps.recsys.service_utils import task_generation

                if not task_generation.is_generator_registered(self.generator_slug):
                    raise ValidationError(
                        {"generator_slug": "Указанный генератор не зарегистрирован"}
                    )
            elif mode == self.DynamicMode.PRE_GENERATED:
                if self.generator_slug:
                    raise ValidationError(
                        {"generator_slug": "Предгенерированные задачи не используют генератор"}
                    )
            else:  # pragma: no cover - defensive branch
                raise ValidationError({"dynamic_mode": "Unsupported dynamic mode"})
        else:
            if self.generator_slug:
                raise ValidationError(
                    {"generator_slug": "Статические задачи не используют генератор"}
                )
            self.dynamic_mode = self.DynamicMode.GENERATOR

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def get_scoring_scheme(self) -> str:
        return self.scoring_scheme or self.type.scoring_scheme

    def get_max_score(self) -> int:
        return int(self.max_score or self.type.max_score or 1)

    def get_answer_schema(self) -> "AnswerSchema | None":
        return self.answer_schema or self.type.answer_schema

    @property
    def uses_pre_generated_data(self) -> bool:
        return self.is_dynamic and self.dynamic_mode == self.DynamicMode.PRE_GENERATED

    def _render_with_payload(
        self,
        payload: Mapping[str, object] | None,
        *,
        highlight: bool,
    ) -> str:
        template = self.description or ""
        if not template:
            return ""

        formatter = Formatter()
        resolved_payload = payload or {}
        fragments: list[str] = []

        for literal_text, field_name, format_spec, conversion in formatter.parse(template):
            fragments.append(literal_text or "")
            if not field_name:
                continue

            value = resolved_payload.get(field_name, f"{{{field_name}}}")

            try:
                formatted_value = format(value, format_spec) if format_spec else value
            except Exception:  # pragma: no cover - defensive fallback
                formatted_value = value

            text_value = str(formatted_value)
            if highlight:
                highlighted = f"{{{text_value}}}"
                fragments.append(f'<span class="task-placeholder">{highlighted}</span>')
            else:
                fragments.append(text_value)

        return "".join(fragments)

    def render_template_preview(self) -> str:
        if not self.uses_pre_generated_data:
            return self.description
        preview = self._render_with_payload(self.default_payload or {}, highlight=True)
        if not preview:
            return self.description
        return mark_safe(sanitize_html(preview))

    def render_template_payload(self, payload: Mapping[str, object] | None) -> str:
        rendered = self._render_with_payload(payload, highlight=False)
        if not rendered:
            return self.description or ""
        return rendered

    def pick_pregenerated_dataset(self, seed: int) -> "TaskPreGeneratedDataset | None":
        if not self.uses_pre_generated_data:
            return None
        queryset = self.pregenerated_datasets.filter(is_active=True)
        total = queryset.count()
        if total == 0:
            return None
        index = seed % total
        return queryset.order_by("id")[index]


class TaskAttachment(TimeStampedModel):
    class Kind(models.TextChoices):
        FILE = "file", "File"
        IMAGE = "image", "Image"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attachments")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.FILE)
    file = models.FileField(upload_to=task_attachment_upload_to)
    label = models.CharField(
        max_length=50,
        blank=True,
        help_text="Optional marker like A/B or 01 for multiple files.",
    )
    download_name_override = models.CharField(
        max_length=255,
        blank=True,
        help_text="If set, this name is suggested for download instead of slug-based.",
    )
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["task", "kind", "order", "id"]
        indexes = [
            models.Index(fields=["task", "kind", "order"]),
        ]

    def __str__(self) -> str:
        return f"{self.task.slug or self.task_id} ({self.kind})"

    @property
    def public_url(self) -> str:
        try:
            raw = self.file.url
        except Exception:
            return ""
        return resolve_media_url(raw)


class TaskPlacement(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        ACTIVE = "active", "Доступно"
        RETIRED = "retired", "Исключено из выдачи"

    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="placements")
    task_type = models.ForeignKey(TaskType, on_delete=models.PROTECT, related_name="placements")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    scoring_scheme = models.CharField(max_length=32, choices=TaskType.ScoringScheme.choices, blank=True)
    max_score = models.PositiveSmallIntegerField(null=True, blank=True)
    answer_schema = models.ForeignKey(AnswerSchema, on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["task", "task_type"], name="task_placement_unique")]
        indexes = [models.Index(fields=["task_type", "status"], name="placement_type_status_idx")]

    def __str__(self):
        return f"{self.task} → {self.task_type}"

    def clean(self):
        super().clean()
        if self.task_id and self.task_type_id:
            if self.task.subject_id != self.task_type.subject_id or not self.task_type.exam_version_id:
                raise ValidationError("Назначение требует годового типа того же предмета.")
            if self.task_type.exam_version.subject_id != self.task.subject_id:
                raise ValidationError("Предмет экзамена не совпадает с задачей.")
        if self.max_score is not None and self.max_score < 1:
            raise ValidationError({"max_score": "Максимум должен быть положительным."})
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if (old.task_id, old.task_type_id) != (self.task_id, self.task_type_id):
                raise ValidationError("Создайте новое назначение вместо переноса существующего.")
            if self.attempts.exists() or self.training_steps.exists() or self.variant_tasks.filter(task_attempts__isnull=False).exists():
                for field in ("scoring_scheme", "max_score", "answer_schema_id"):
                    if getattr(old, field) != getattr(self, field):
                        raise ValidationError("Использованное оценивание зафиксировано; создайте новую редакцию экзамена.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ExamProgressSnapshot(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="exam_progress_snapshots")
    exam_version = models.ForeignKey("ExamVersion", on_delete=models.PROTECT, related_name="progress_snapshots")
    as_of = models.DateTimeField(default=timezone.now)
    algorithm_version = models.CharField(max_length=64, default="exam-progress-v1")
    purpose = models.CharField(max_length=32, default="archive")
    data = models.JSONField(default=dict)

    class Meta:
        ordering = ["-as_of", "-pk"]
        constraints = [models.UniqueConstraint(fields=["user", "exam_version", "purpose", "as_of"], name="exam_progress_snapshot_unique")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Снимок прогресса неизменяем; создайте новый снимок.")
        return super().save(*args, **kwargs)


class TaskTypeTransition(TimeStampedModel):
    class Relation(models.TextChoices):
        EQUIVALENT = "equivalent", "Соответствует"
        PARTIAL = "partial", "Частично"
        SPLIT = "split", "Разделение"
        MERGE = "merge", "Объединение"
        ADDED = "added", "Новый тип"
        REMOVED = "removed", "Исключённый тип"

    target_exam = models.ForeignKey("ExamVersion", on_delete=models.PROTECT, related_name="type_transitions")
    source_type = models.ForeignKey(TaskType, on_delete=models.PROTECT, null=True, blank=True, related_name="outgoing_transitions")
    target_type = models.ForeignKey(TaskType, on_delete=models.PROTECT, null=True, blank=True, related_name="incoming_transitions")
    relation = models.CharField(max_length=16, choices=Relation.choices, default=Relation.EQUIVALENT)
    approved = models.BooleanField(default=False)
    task_ids = models.JSONField(default=list, blank=True, help_text="Явный набор задач для частичного соответствия.")
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["target_exam", "source_type", "target_type"], name="type_transition_unique")]

    def __str__(self):
        return f"{self.source_type or 'Новый'} → {self.target_type or 'Исключён'}"

    def clean(self):
        super().clean()
        if not self.source_type_id and not self.target_type_id:
            raise ValidationError("Укажите исходный или новый тип.")
        if self.target_type_id and self.target_type.exam_version_id != self.target_exam_id:
            raise ValidationError("Новый тип должен относиться к выбранному экзамену.")
        if self.source_type_id and (self.source_type.subject_id != self.target_exam.subject_id or self.source_type.exam_version_id == self.target_exam_id):
            raise ValidationError("Исходный тип должен относиться к другому экзамену того же предмета.")
        if self.relation == self.Relation.ADDED and (self.source_type_id or not self.target_type_id):
            raise ValidationError("Для нового типа укажите только целевой тип.")
        if self.relation == self.Relation.REMOVED and (not self.source_type_id or self.target_type_id):
            raise ValidationError("Для исключения укажите только исходный тип.")
        if self.relation not in {self.Relation.ADDED, self.Relation.REMOVED} and not (self.source_type_id and self.target_type_id):
            raise ValidationError("Для соответствия нужны оба типа.")
        if not isinstance(self.task_ids, list) or any(type(value) is not int or value <= 0 for value in self.task_ids):
            raise ValidationError({"task_ids": "Ожидается список положительных ID задач."})
        if self.target_exam.published_at:
            raise ValidationError("Соответствия опубликованного экзамена зафиксированы.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class TaskSkill(TimeStampedModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE)
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE)
    weight = models.FloatField(default=1.0)

    def clean(self):
        if self.task.subject_id != self.skill.subject_id:
            raise ValidationError("Task and Skill must have the same subject")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        unique_together = ("task", "skill")
        indexes = [
            models.Index(fields=["task"]),
            models.Index(fields=["skill"]),
        ]

    def __str__(self) -> str:
        return f"{self.task} - {self.skill}"


class ExamVersion(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Архив"

    exam_kind = models.CharField(max_length=32, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    revision = models.PositiveSmallIntegerField(default=1)
    is_default = models.BooleanField(default=False)
    copied_from = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="successors")
    publication_info = models.JSONField(default=dict, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="exam_versions"
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=128, null=True, blank=True, db_index=True)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
        null=True,
        blank=True,
        db_index=True,
    )
    start_info = models.TextField(
        blank=True,
        help_text="Reference info shown at the start of the exam.",
    )

    class Meta:
        ordering = ["subject__name", "name"]
        unique_together = ("subject", "name")
        constraints = [
            models.UniqueConstraint(fields=["subject", "exam_kind", "year", "revision"], name="exam_year_revision_unique"),
            models.UniqueConstraint(fields=["subject", "exam_kind"], condition=models.Q(is_default=True), name="exam_default_unique"),
        ]
        indexes = [
            models.Index(fields=["subject", "name"]),
            models.Index(fields=["slug"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.subject.name} — {self.name}"

    def _normalize_slug(self) -> None:
        raw_slug = self.slug or self.name
        normalized = slugify(raw_slug or "")
        if normalized:
            self.slug = normalized

    def save(self, *args, **kwargs):
        self._normalize_slug()
        if not self.status:
            self.status = self.Status.DRAFT
        return super().save(*args, **kwargs)


class ExamScoreScale(TimeStampedModel):
    exam_version = models.OneToOneField(
        ExamVersion,
        on_delete=models.CASCADE,
        related_name="score_scale",
    )
    max_primary = models.PositiveSmallIntegerField(
        help_text="Maximum primary score supported by this scale.",
    )
    mapping = models.JSONField(
        default=list,
        blank=True,
        help_text="List where index=primary score and value=secondary score.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["exam_version"]

    def __str__(self) -> str:  # pragma: no cover - human readable
        return f"{self.exam_version} scale"

    def clean(self):
        super().clean()
        if self.mapping is None:
            self.mapping = []
        if not isinstance(self.mapping, list):
            raise ValidationError({"mapping": "Scale mapping must be a list."})
        if self.max_primary is None:
            raise ValidationError({"max_primary": "Max primary score is required."})
        if len(self.mapping) != int(self.max_primary) + 1:
            raise ValidationError(
                {"mapping": "Mapping length must be max_primary + 1."}
            )
        for idx, value in enumerate(self.mapping):
            if not isinstance(value, int):
                raise ValidationError({"mapping": f"Mapping value #{idx} must be integer."})
            if value < 0:
                raise ValidationError({"mapping": f"Mapping value #{idx} must be non-negative."})

    def to_secondary(self, primary_score: int) -> tuple[int | None, bool]:
        if primary_score < 0:
            primary_score = 0
        if primary_score > self.max_primary:
            return None, True
        return int(self.mapping[int(primary_score)]), False


class SkillGroup(TimeStampedModel):
    exam_version = models.ForeignKey(
        ExamVersion, on_delete=models.CASCADE, related_name="skill_groups"
    )
    title = models.CharField(max_length=255)

    class Meta:
        unique_together = ("exam_version", "title")
        ordering = ["exam_version", "id"]

    def __str__(self) -> str:
        return self.title


class SkillGroupItem(TimeStampedModel):
    group = models.ForeignKey(
        SkillGroup, on_delete=models.CASCADE, related_name="items"
    )
    skill = models.ForeignKey(
        Skill, on_delete=models.CASCADE, related_name="group_items"
    )
    label = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("group", "skill")
        ordering = ["order"]
        indexes = [
            models.Index(fields=["group"]),
            models.Index(fields=["skill"]),
        ]

    def __str__(self) -> str:
        return f"{self.group} - {self.label}"


class Attempt(TimeStampedModel):
    placement = models.ForeignKey("TaskPlacement", on_delete=models.PROTECT, null=True, blank=True, related_name="attempts")
    exam_version = models.ForeignKey("ExamVersion", on_delete=models.PROTECT, null=True, blank=True, related_name="recorded_attempts")
    task_type = models.ForeignKey("TaskType", on_delete=models.PROTECT, null=True, blank=True, related_name="recorded_attempts")
    context_origin = models.CharField(max_length=20, default="unknown")
    context_snapshot = models.JSONField(default=dict, blank=True)
    task_snapshot = models.JSONField(default=dict, blank=True)
    response_snapshot = models.JSONField(default=dict, blank=True)
    submission_key = models.UUIDField(null=True, blank=True)

    class Mode(models.TextChoices):
        TRAINING = "training", "Training"
        VARIANT = "variant", "Variant"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts"
    )
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="attempts")
    is_correct = models.BooleanField(default=False)
    attempts_count = models.PositiveIntegerField(default=1)
    attempt_number = models.PositiveIntegerField(default=1)
    score = models.FloatField(null=True, blank=True)
    max_score = models.PositiveSmallIntegerField(default=1)
    time_spent = models.DurationField(null=True, blank=True)
    is_valid_attempt = models.BooleanField(default=True)
    mode = models.CharField(
        max_length=16,
        choices=Mode.choices,
        default=Mode.TRAINING,
    )
    checked_at = models.DateTimeField(null=True, blank=True)
    variant_task_attempt = models.ForeignKey(
        "VariantTaskAttempt",
        on_delete=models.PROTECT,
        related_name="attempts",
        null=True,
        blank=True,
    )
    source_recommendation = models.ForeignKey(
        "RecommendationLog",
        on_delete=models.SET_NULL,
        related_name="attempts",
        null=True,
        blank=True,
    )
    weight = models.FloatField(default=1.0)

    class Meta:
        indexes = [models.Index(fields=["user", "task"]), models.Index(fields=["user", "exam_version", "task_type", "created_at"], name="attempt_exam_history_idx")]
        constraints = [
            models.UniqueConstraint(fields=["user", "submission_key"], name="attempt_submission_unique"),
            models.UniqueConstraint(fields=["variant_task_attempt"], condition=models.Q(variant_task_attempt__isnull=False, context_origin="issued"), name="attempt_variant_answer_unique"),
        ]

    def save(self, *args, **kwargs):
        from .service_utils.exam_context import prepare_attempt_context
        if self._state.adding:
            prepare_attempt_context(self)
        else:
            old = type(self).objects.filter(pk=self.pk).values("task_id", "placement_id", "exam_version_id", "task_type_id", "context_snapshot", "task_snapshot", "response_snapshot").first()
            if old and any(getattr(self, key) != value for key, value in old.items()):
                raise ValidationError("Контекст сохранённого ответа нельзя менять.")
        from django.db import transaction
        from django.contrib.auth import get_user_model
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=self.user_id)
            self.task = Task.objects.select_for_update().get(pk=self.task_id)
            return super().save(*args, **kwargs)

    def __str__(self) -> str:
        status = "correct" if self.is_correct else "incorrect"
        return f"{self.user} - {self.task} ({status})"


class SkillMastery(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="skill_masteries"
    )
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="masteries")
    mastery = models.FloatField(default=0.0)
    confidence = models.FloatField(default=0.0)

    class Meta:
        unique_together = ("user", "skill")
        indexes = [models.Index(fields=["user", "skill"])]

    def __str__(self) -> str:
        return f"{self.user} - {self.skill}: {self.mastery}"


class TagMastery(TimeStampedModel):
    decayed_at = models.DateTimeField(null=True, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tag_masteries"
    )
    task_tag = models.ForeignKey(
        TaskTag, on_delete=models.CASCADE, related_name="masteries"
    )
    mastery = models.FloatField(default=0.0)
    coverage = models.FloatField(default=0.0)
    progress = models.FloatField(default=0.0)
    confidence = models.FloatField(default=0.0)
    stability = models.FloatField(default=0.0)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    attempts_total = models.PositiveIntegerField(default=0)
    successes_total = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("user", "task_tag")
        indexes = [models.Index(fields=["user", "task_tag"])]

    def __str__(self) -> str:
        return f"{self.user} - {self.task_tag}: {self.mastery}"


class TypeMastery(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="type_masteries"
    )
    task_type = models.ForeignKey(
        TaskType, on_delete=models.CASCADE, related_name="masteries"
    )
    mastery = models.FloatField(default=0.0)
    coverage = models.FloatField(default=0.0)
    progress = models.FloatField(default=0.0)
    confidence = models.FloatField(default=0.0)
    stability = models.FloatField(default=0.0)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    attempts_total = models.PositiveIntegerField(default=0)
    successes_total = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("user", "task_type")
        indexes = [models.Index(fields=["user", "task_type"])]

    def __str__(self) -> str:
        return f"{self.user} - {self.task_type}: {self.mastery}"


class RecommendationLog(TimeStampedModel):
    task_snapshot = models.JSONField(default=dict, blank=True)
    class Status(models.TextChoices):
        RECOMMENDED = "recommended", "Recommended"
        OPENED = "opened", "Opened"
        ATTEMPTED = "attempted", "Attempted"
        COMPLETED = "completed", "Completed"
        DISMISSED = "dismissed", "Dismissed"

    class SourceMode(models.TextChoices):
        TRAINING = "training", "Training"
        VARIANT = "variant", "Variant"
        BATCH = "batch", "Batch"
        UNKNOWN = "unknown", "Unknown"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recommendation_logs"
    )
    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name="recommendation_logs"
    )
    completed = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.RECOMMENDED,
    )
    recommended_at = models.DateTimeField(null=True, blank=True)
    source_mode = models.CharField(
        max_length=16,
        choices=SourceMode.choices,
        default=SourceMode.UNKNOWN,
    )
    rank_position = models.PositiveIntegerField(null=True, blank=True)
    score_snapshot = models.JSONField(default=dict, blank=True)
    reason_snapshot = models.JSONField(default=dict, blank=True)
    weak_tags_snapshot = models.JSONField(default=list, blank=True)
    coverage_gain_snapshot = models.FloatField(null=True, blank=True)
    spacing_gain_snapshot = models.FloatField(null=True, blank=True)
    attempt = models.ForeignKey(
        Attempt,
        on_delete=models.SET_NULL,
        related_name="recommendation_logs",
        null=True,
        blank=True,
    )

    class Meta:
        indexes = [models.Index(fields=["user", "task"])]

    def __str__(self) -> str:
        return f"{self.user} - {self.task}"


class TrainingSession(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        ABANDONED = "abandoned", "Abandoned"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="training_sessions",
    )
    exam_version = models.ForeignKey(
        ExamVersion,
        on_delete=models.CASCADE,
        related_name="training_sessions",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    selected_task_type_ids = models.JSONField(default=list, blank=True)
    steps_total = models.PositiveIntegerField(default=0)
    completed_steps = models.PositiveIntegerField(default=0)
    correct_steps = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-started_at", "-id"]
        indexes = [
            models.Index(fields=["user", "exam_version", "status"]),
            models.Index(fields=["user", "status"]),
        ]

    def mark_activity(self) -> None:
        now = timezone.now()
        self.last_activity_at = now
        self.save(update_fields=["last_activity_at", "updated_at"])

    def mark_completed(self) -> None:
        if self.status == self.Status.COMPLETED:
            return
        now = timezone.now()
        self.status = self.Status.COMPLETED
        self.last_activity_at = now
        self.ended_at = now
        self.save(update_fields=["status", "last_activity_at", "ended_at", "updated_at"])

    def mark_abandoned(self) -> None:
        if self.status == self.Status.ABANDONED:
            return
        now = timezone.now()
        self.status = self.Status.ABANDONED
        self.last_activity_at = now
        self.ended_at = now
        self.save(update_fields=["status", "last_activity_at", "ended_at", "updated_at"])

    def __str__(self) -> str:
        return f"Training session {self.id} for {self.user}"

    def clean(self):
        super().clean()
        value = self.selected_task_type_ids or []
        if not isinstance(value, list):
            raise ValidationError({"selected_task_type_ids": "Value must be a list of task type ids."})
        normalized: list[int] = []
        seen: set[int] = set()
        for item in value:
            try:
                type_id = int(item)
            except (TypeError, ValueError) as exc:
                raise ValidationError({"selected_task_type_ids": "Each task type id must be an integer."}) from exc
            if type_id <= 0:
                raise ValidationError({"selected_task_type_ids": "Each task type id must be positive."})
            if type_id in seen:
                continue
            seen.add(type_id)
            normalized.append(type_id)
        self.selected_task_type_ids = normalized


class TrainingSessionStep(TimeStampedModel):
    placement = models.ForeignKey("TaskPlacement", on_delete=models.PROTECT, null=True, blank=True, related_name="training_steps")
    class Status(models.TextChoices):
        RECOMMENDED = "recommended", "Recommended"
        OPENED = "opened", "Opened"
        ANSWERED = "answered", "Answered"
        SKIPPED = "skipped", "Skipped"

    class Result(models.TextChoices):
        CORRECT = "correct", "Correct"
        INCORRECT = "incorrect", "Incorrect"
        PARTIAL = "partial", "Partial"
        UNKNOWN = "unknown", "Unknown"

    session = models.ForeignKey(
        TrainingSession,
        on_delete=models.CASCADE,
        related_name="steps",
    )
    order = models.PositiveIntegerField(default=1)
    task = models.ForeignKey(
        Task,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="training_steps",
    )
    recommendation_log = models.ForeignKey(
        RecommendationLog,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="training_steps",
    )
    attempt = models.ForeignKey(
        Attempt,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="training_session_steps",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.RECOMMENDED,
    )
    result = models.CharField(
        max_length=16,
        choices=Result.choices,
        default=Result.UNKNOWN,
    )
    task_snapshot = models.JSONField(default=dict, blank=True)
    response_snapshot = models.JSONField(default=dict, blank=True)
    reason_snapshot = models.JSONField(default=dict, blank=True)
    shown_at = models.DateTimeField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["session", "order", "id"]
        unique_together = ("session", "order")
        indexes = [
            models.Index(fields=["session", "order"]),
            models.Index(fields=["task"]),
            models.Index(fields=["recommendation_log"]),
        ]

    def __str__(self) -> str:
        return f"Training step {self.order} for session {self.session_id}"


class ExamBlueprint(TimeStampedModel):
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="exam_blueprints",
    )
    exam_version = models.OneToOneField(
        ExamVersion,
        on_delete=models.CASCADE,
        related_name="blueprint",
    )
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    time_limit = models.DurationField(null=True, blank=True)
    max_attempts = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["exam_version"]
        indexes = [
            models.Index(fields=["exam_version", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.title or f"Blueprint for {self.exam_version}"

    def clean(self):
        super().clean()
        if self.exam_version and self.exam_version.subject_id != self.subject_id:
            raise ValidationError({"exam_version": "Exam version must match blueprint subject."})


class ExamBlueprintItem(TimeStampedModel):
    blueprint = models.ForeignKey(
        ExamBlueprint,
        on_delete=models.CASCADE,
        related_name="items",
    )
    task_type = models.ForeignKey(
        TaskType,
        on_delete=models.CASCADE,
        related_name="blueprint_items",
    )
    count = models.PositiveIntegerField(default=1)
    order = models.PositiveIntegerField(default=1)
    section = models.CharField(max_length=64, blank=True)
    score_override = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["blueprint", "task_type"],
                name="blueprint_task_type_unique",
            ),
            models.UniqueConstraint(
                fields=["blueprint", "order"],
                name="blueprint_order_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["blueprint", "order"]),
        ]

    def __str__(self) -> str:
        return f"{self.blueprint} -> {self.task_type} x{self.count}"

    def clean(self):
        super().clean()
        if self.task_type and self.blueprint:
            if self.task_type.subject_id != self.blueprint.subject_id:
                raise ValidationError({"task_type": "Task type must match blueprint subject."})
            if (
                self.task_type.exam_version_id
                and self.blueprint.exam_version_id
                and self.task_type.exam_version_id != self.blueprint.exam_version_id
            ):
                raise ValidationError({"task_type": "Task type must match blueprint exam version."})


class VariantPage(TimeStampedModel):
    template = models.OneToOneField(
        "VariantTemplate",
        on_delete=models.CASCADE,
        related_name="page",
    )
    slug = models.SlugField(max_length=128, unique=True, db_index=True)
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    is_public = models.BooleanField(default=True)

    class Meta:
        ordering = ["slug"]
        indexes = [models.Index(fields=["slug"])]

    def __str__(self) -> str:  # pragma: no cover - human readable
        return self.title or self.template.name

    def _normalize_slug(self) -> None:
        normalized = slugify(self.slug or self.title or self.template.name or "")
        if normalized:
            self.slug = normalized

    def save(self, *args, **kwargs):
        self._normalize_slug()
        return super().save(*args, **kwargs)


class VariantTemplate(TimeStampedModel):
    class Kind(models.TextChoices):
        PERSONAL = "personal", "Personal"
        DEMO = "demo", "Demo"
        OFFICIAL = "official", "Official/EGKR"
        BOOK = "book", "Book collection"
        TEACHER = "teacher", "Teacher draft"
        CUSTOM = "custom", "Custom"

    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    exam_version = models.ForeignKey(
        ExamVersion,
        on_delete=models.CASCADE,
        related_name="variant_templates",
        null=True,
        blank=True,
    )
    slug = models.SlugField(max_length=128, null=True, blank=True, db_index=True)
    kind = models.CharField(
        max_length=32,
        choices=Kind.choices,
        default=Kind.CUSTOM,
    )
    is_public = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)
    time_limit = models.DurationField(null=True, blank=True)
    max_attempts = models.PositiveIntegerField(null=True, blank=True)
    tasks = models.ManyToManyField(
        Task, through="VariantTask", related_name="variant_templates"
    )

    class Meta:
        ordering = ["display_order", "name"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["exam_version", "is_public", "display_order"]),
        ]

    def __str__(self) -> str:
        return self.name

    def _normalize_slug(self) -> None:
        raw_slug = self.slug or self.name
        normalized = slugify(raw_slug or "")
        if normalized:
            self.slug = normalized

    def save(self, *args, **kwargs):
        self._normalize_slug()
        return super().save(*args, **kwargs)


class VariantTask(TimeStampedModel):
    placement = models.ForeignKey("TaskPlacement", on_delete=models.PROTECT, null=True, blank=True, related_name="variant_tasks")
    template = models.ForeignKey(
        VariantTemplate, on_delete=models.CASCADE, related_name="template_tasks"
    )
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="variant_tasks")
    order = models.PositiveIntegerField()
    max_attempts = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["template", "order"]
        unique_together = (
            ("template", "order"),
            ("template", "task"),
        )
        indexes = [
            models.Index(fields=["template", "order"]),
            models.Index(fields=["template", "task"]),
        ]

    def save(self, *args, **kwargs):
        from .service_utils.exam_context import resolve_placement
        if self._state.adding and self.template.assignments.filter(attempts__isnull=False).exists():
            raise ValidationError("Уже начатый вариант нельзя дополнять. Создайте новый шаблон.")
        if self._state.adding and self.template.exam_version_id:
            self.placement = resolve_placement(self.task, exam_version=self.template.exam_version, placement=self.placement)
        if self.pk and self.task_attempts.exists():
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(old, name) != getattr(self, name) for name in ("task_id", "template_id", "placement_id", "order")):
                raise ValidationError("Состав уже начатого варианта нельзя переназначить.")
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.template} -> {self.task}"


class VariantAssignment(TimeStampedModel):
    template = models.ForeignKey(
        VariantTemplate, on_delete=models.CASCADE, related_name="assignments"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="variant_assignments",
    )
    deadline = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["template"]),
            models.Index(fields=["user", "template"]),
        ]

    def mark_started(self) -> None:
        if self.started_at is None:
            self.started_at = timezone.now()
            self.save(update_fields=["started_at", "updated_at"])

    def __str__(self) -> str:
        return f"{self.user} - {self.template}"


class VariantAttempt(TimeStampedModel):
    exam_snapshot = models.JSONField(default=dict, blank=True)
    assignment = models.ForeignKey(
        VariantAssignment, on_delete=models.CASCADE, related_name="attempts"
    )
    attempt_number = models.PositiveIntegerField(default=1)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    time_spent = models.DurationField(null=True, blank=True)
    active_variant_task = models.ForeignKey(
        "VariantTask",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Variant task currently opened by the student (for per-task timers).",
    )
    active_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the current task timer was started.",
    )
    last_seen_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last heartbeat time for the attempt.",
    )
    active_client_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="Client id of the active attempt tab.",
    )

    class Meta:
        ordering = ["assignment", "attempt_number"]
        unique_together = ("assignment", "attempt_number")
        indexes = [
            models.Index(fields=["assignment", "attempt_number"]),
            models.Index(fields=["assignment"]),
        ]

    def mark_completed(self) -> None:
        if self.completed_at is None:
            self.completed_at = timezone.now()
            if self.time_spent is None:
                self.time_spent = self.completed_at - self.started_at
            self.save(update_fields=["completed_at", "time_spent", "updated_at"])

    def __str__(self) -> str:
        return f"Attempt {self.attempt_number} for {self.assignment}"


class VariantTaskAttempt(TimeStampedModel):
    submission_key = models.UUIDField(null=True, blank=True, unique=True)
    variant_attempt = models.ForeignKey(
        VariantAttempt, on_delete=models.CASCADE, related_name="task_attempts"
    )
    variant_task = models.ForeignKey(
        VariantTask, on_delete=models.PROTECT, related_name="task_attempts"
    )
    task = models.ForeignKey(
        Task,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="variant_task_attempts",
    )
    attempt_number = models.PositiveIntegerField(default=1)
    is_correct = models.BooleanField(default=False)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    max_score = models.PositiveSmallIntegerField(default=1)
    task_snapshot = models.JSONField(default=dict, blank=True)
    time_spent = models.DurationField(null=True, blank=True)
    is_valid_attempt = models.BooleanField(default=True)
    checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["variant_attempt", "variant_task", "attempt_number"]
        unique_together = ("variant_attempt", "variant_task", "attempt_number")
        indexes = [
            models.Index(fields=["variant_attempt"]),
            models.Index(fields=["variant_task"]),
        ]

    def __str__(self) -> str:
        return (
            f"Task attempt {self.attempt_number} for {self.variant_task} "
            f"(variant attempt {self.variant_attempt.attempt_number})"
        )


class TaskPreGeneratedDataset(TimeStampedModel):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="pregenerated_datasets",
    )
    parameter_values = models.JSONField(default=dict, blank=True)
    correct_answer = models.JSONField(default=dict, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["task", "id"]
        indexes = [
            models.Index(fields=["task", "is_active"]),
        ]
        verbose_name = "Pre-generated dataset"
        verbose_name_plural = "Pre-generated datasets"

    def __str__(self) -> str:  # pragma: no cover - human-readable representation
        return f"Dataset #{self.pk} for {self.task}"


class VariantTaskTimeLog(TimeStampedModel):
    class StopReason(models.TextChoices):
        SWITCH = "switch", "Switched to another task"
        SAVE = "save", "Answer saved"
        SUBMIT = "submit", "Answer submitted"
        FINALIZE = "finalize", "Attempt finalized"
        CLEAR = "clear", "Answer cleared"
        ATTEMPT_TIMEOUT = "attempt_timeout", "Attempt time limit reached"
        AUTO = "auto", "Auto stop"

    variant_attempt = models.ForeignKey(
        VariantAttempt,
        on_delete=models.CASCADE,
        related_name="time_logs",
    )
    variant_task = models.ForeignKey(
        VariantTask,
        on_delete=models.CASCADE,
        related_name="time_logs",
    )
    started_at = models.DateTimeField()
    stopped_at = models.DateTimeField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)
    stop_reason = models.CharField(
        max_length=16,
        choices=StopReason.choices,
        default=StopReason.SWITCH,
    )
    auto_stopped = models.BooleanField(default=False)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["variant_attempt", "variant_task", "stopped_at"]),
            models.Index(fields=["variant_attempt", "stopped_at"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - human readable
        task_label = f"{self.variant_task_id}" if self.variant_task_id else "?"
        return f"Time log for task {task_label} (attempt {self.variant_attempt_id})"
