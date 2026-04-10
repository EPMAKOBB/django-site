# Task Rendering Unification Plan

## 1. Purpose

This document defines how task rendering should be unified across the product before full training-mode implementation begins.

It focuses on one concrete problem:

- the same task may appear in multiple contexts;
- the body of the task should look the same everywhere;
- answer input UI should not be coupled to the task statement itself.

This document is implementation-oriented and should guide the next backend and template refactor.

## 2. Problem Statement

The task card currently appears in four product contexts:

1. task-type browsing page;
2. variant preview page;
3. mock-exam solver;
4. future training mode.

Today these contexts do not share one canonical rendering path.

Current state:

- some screens render `description` directly in templates through `render_task_body`;
- solver consumes prebuilt `task_body_html`;
- surrounding markup and CSS scopes differ between pages;
- statement rendering and answer-input rendering are still partially entangled at the page level.

This creates several risks:

- visual drift between contexts;
- inconsistent handling of markdown, HTML, tables, formulas, and images;
- duplicated template branches for `html / markdown / plain`;
- harder training-mode implementation because it would need to pick one of multiple existing rendering approaches.

## 3. Main Decision

The system should standardize on one canonical presentation field:

- `task_body_html`

All user-facing task surfaces should render the task statement from this prepared HTML field instead of rebuilding statement HTML independently inside page templates.

The task statement and the answer UI must be treated as separate product layers:

- `task statement` = condition, formulas, tables, images, attachments;
- `task response UI` = answer fields, save/submit actions, feedback, correctness state.

## 4. Canonical Rendering Principles

### 4.1 One Rendering Pipeline

There must be exactly one backend rendering pipeline that converts:

- source statement content;
- rendering strategy;
- generated snapshot overrides where relevant;

into:

- safe final HTML for display.

The existing utility in [apps/recsys/utils/rendering.py](D:/FS/django-site/apps/recsys/utils/rendering.py) should remain the canonical low-level renderer.

### 4.2 One Presentation Contract

Every screen that displays a task should consume the same presentation-level payload instead of improvising from raw model fields.

Minimum contract:

- `task_id`
- `title`
- `task_body_html`
- `task_rendering_strategy`
- `image`
- `attachments`
- `answer_schema`
- `max_score`
- `task_type_name`

Optional context-specific fields may be added later, but the statement payload should stay canonical.

### 4.3 Snapshot First

When a generated or snapshotted task representation exists, it should be the source of truth for statement rendering.

Order of precedence:

1. generated snapshot statement;
2. persisted task snapshot statement;
3. model-level `Task.description`.

This prevents the displayed statement from drifting between preview, solving, review, and future training flows.

### 4.4 Server-Side Rendering of Statement HTML

Templates should not decide how to transform markdown or HTML into final statement markup.

Templates should only:

- receive `task_body_html`;
- place it into a canonical statement container;
- render optional image / attachment blocks around it.

This keeps sanitization, markdown extensions, and formula protection centralized.

## 5. Required Separation of Concerns

## 5.1 Task Statement Component

The task statement component is responsible for:

- condition text;
- tables;
- formulas;
- images;
- attachments;
- statement-level fallback if content is missing.

It must not contain:

- answer fields;
- save / submit buttons;
- correctness badges tied to the active response flow.

## 5.2 Task Response Component

The response component is responsible for:

- answer-schema-driven inputs;
- draft state;
- submit / save / clear actions;
- feedback after submission;
- correct-answer reveal if the mode allows it.

It must not own statement rendering rules.

## 6. Target File Architecture

## 6.1 Backend Renderer and Presenter Layer

The low-level renderer already exists in:

- [apps/recsys/utils/rendering.py](D:/FS/django-site/apps/recsys/utils/rendering.py)

The next step should be to add a presentation builder layer, for example:

- `apps/recsys/presentation/tasks.py`

Suggested responsibilities:

- build one normalized task presentation dict;
- choose snapshot vs model source;
- call the canonical body renderer;
- normalize image and attachments;
- return the same fields for preview, solver, and training mode.

Suggested API shape:

```python
build_task_presentation(...)
build_task_statement_payload(...)
```

The exact function names may vary, but the role should be explicit: this is a presenter layer, not raw model access.

## 6.2 Shared Statement Template

Create one canonical partial:

- `templates/recsys/components/task_statement.html`

Expected inputs:

- `task_body_html`
- `image`
- `attachments`
- `empty_message`
- optional modifier classes

This partial should be used by:

- [templates/exams/type_detail.html](D:/FS/django-site/templates/exams/type_detail.html)
- [templates/variants/detail.html](D:/FS/django-site/templates/variants/detail.html)
- [accounts/templates/accounts/dashboard/variant_attempt_solver.html](D:/FS/django-site/accounts/templates/accounts/dashboard/variant_attempt_solver.html)
- future training-mode template

## 6.3 Shared Response Template

Create a separate response partial family later, for example:

- `templates/recsys/components/task_response_panel.html`

This should be introduced after statement unification starts, because the current urgent problem is statement rendering consistency.

## 6.4 Shared Styling Scope

Create one canonical CSS scope for statement content, for example inside:

- `static/css/task-statement.css`

Primary scope:

- `.task-statement`

Required styling targets:

- paragraphs;
- lists;
- headings;
- tables;
- horizontal overflow for wide tables;
- inline and block code;
- blockquotes;
- images;
- KaTeX blocks and inline math;
- spacing between semantic elements.

This stylesheet should be loaded anywhere a task statement may appear.

## 7. Migration of Existing Screens

## 7.1 Task-Type Page

Current template:

- [templates/exams/type_detail.html](D:/FS/django-site/templates/exams/type_detail.html)

Current issue:

- the template still branches directly on `rendering_strategy`.

Migration target:

- view prepares `task_body_html`;
- template includes `task_statement.html`;
- no local `markdown / html / plain` branching remains.

## 7.2 Variant Preview

Current template:

- [templates/variants/detail.html](D:/FS/django-site/templates/variants/detail.html)

Current issue:

- statement rendering is duplicated in template logic.

Migration target:

- prepare one presentation payload per preview task;
- render the same shared statement partial used by the task-type page.

## 7.3 Solver

Current template:

- [accounts/templates/accounts/dashboard/variant_attempt_solver.html](D:/FS/django-site/accounts/templates/accounts/dashboard/variant_attempt_solver.html)

Current state:

- solver already consumes `task_body_html`, which is the correct architectural direction.

Migration target:

- keep solver on the same canonical payload;
- align solver DOM container and CSS scope with the shared statement component;
- avoid solver-specific statement markup rules unless they are strictly layout-related.

## 7.4 Training Mode

Training mode should be implemented only on top of the unified statement component.

It should not introduce a third rendering path.

Training page target:

- use the same statement payload contract;
- render the same statement partial;
- attach a separate training-specific response panel.

## 8. Rendering Rules for Complex Content

## 8.1 Markdown

Markdown should remain the primary authoring format for normal tasks.

Requirements:

- keep current markdown extensions;
- preserve math fragments before markdown conversion;
- sanitize final HTML after conversion.

## 8.2 HTML

HTML should remain available for advanced statements that require richer layout control.

Requirements:

- continue sanitizing HTML;
- forbid page-breaking styling assumptions inside task HTML;
- rely on the shared `.task-statement` scope for final look.

## 8.3 Formulas

KaTeX is already loaded globally in the main base templates and should remain the standard formula renderer.

Requirements:

- statement markup must be compatible with the current KaTeX auto-render flow;
- all task contexts must use the same statement container so formula initialization behaves consistently;
- any context that injects statement HTML dynamically must explicitly trigger the same math-render pass after DOM update.

This matters especially for:

- solver;
- future training mode.

## 8.4 Tables

Tables must be styled in the shared statement scope, not ad hoc per page.

Requirements:

- consistent typography;
- consistent border and cell padding;
- mobile overflow handling;
- no page-local table styling branches for solver vs preview vs browse mode.

## 9. Proposed Implementation Sequence

1. Keep [apps/recsys/utils/rendering.py](D:/FS/django-site/apps/recsys/utils/rendering.py) as the canonical low-level renderer.
2. Add a task presentation builder in `apps/recsys/presentation/tasks.py`.
3. Introduce `templates/recsys/components/task_statement.html`.
4. Introduce `static/css/task-statement.css`.
5. Migrate task-type page to the new payload and partial.
6. Migrate variant preview page to the new payload and partial.
7. Align solver containers with the same statement partial and CSS scope.
8. Only after that, build training mode on top of the unified statement layer.

## 10. What Should Not Be Done

- Do not create one giant task-card include that mixes statement, answer fields, review state, and action buttons.
- Do not keep direct `rendering_strategy` branching duplicated across multiple templates.
- Do not let training mode invent a new statement renderer.
- Do not make statement styling depend on page-local wrappers only.
- Do not make templates responsible for sanitization or markdown conversion decisions.

## 11. Immediate Outcome Expected from This Plan

After this unification work:

- the same task body should render identically on browse, preview, solver, and training surfaces;
- future training mode can reuse solver-grade statement rendering without inheriting solver-specific workflow constraints;
- answer input systems can evolve independently from task statement presentation;
- complex content such as formulas and tables will have one canonical display path in the product.
