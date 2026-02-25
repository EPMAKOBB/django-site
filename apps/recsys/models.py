from __future__ import annotations

from copy import deepcopy
from string import Formatter
from typing import Mapping
import os

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


def task_attachment_upload_to(instance: "TaskAttachment", filename: str) -> str:
    """
    Store files under tasks/<exam_version>/files|images/<task_slug>-<label>.<ext>
    """
    task = instance.task
    exam_slug = _exam_version_slug(task)
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
    image = models.ImageField(upload_to="tasks/screenshots/", blank=True)
    correct_answer = models.JSONField(blank=True, default=dict)
    difficulty_level = models.PositiveSmallIntegerField(default=0)
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
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts"
    )
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attempts")
    is_correct = models.BooleanField(default=False)
    attempts_count = models.PositiveIntegerField(default=1)
    variant_task_attempt = models.ForeignKey(
        "VariantTaskAttempt",
        on_delete=models.CASCADE,
        related_name="attempts",
        null=True,
        blank=True,
    )
    weight = models.FloatField(default=1.0)

    class Meta:
        indexes = [models.Index(fields=["user", "task"])]

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


class TypeMastery(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="type_masteries"
    )
    task_type = models.ForeignKey(
        TaskType, on_delete=models.CASCADE, related_name="masteries"
    )
    mastery = models.FloatField(default=0.0)
    confidence = models.FloatField(default=0.0)

    class Meta:
        unique_together = ("user", "task_type")
        indexes = [models.Index(fields=["user", "task_type"])]

    def __str__(self) -> str:
        return f"{self.user} - {self.task_type}: {self.mastery}"


class RecommendationLog(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recommendation_logs"
    )
    task = models.ForeignKey(
        Task, on_delete=models.CASCADE, related_name="recommendation_logs"
    )
    completed = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["user", "task"])]

    def __str__(self) -> str:
        return f"{self.user} - {self.task}"


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
    variant_attempt = models.ForeignKey(
        VariantAttempt, on_delete=models.CASCADE, related_name="task_attempts"
    )
    variant_task = models.ForeignKey(
        VariantTask, on_delete=models.CASCADE, related_name="task_attempts"
    )
    task = models.ForeignKey(
        Task,
        on_delete=models.SET_NULL,
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
