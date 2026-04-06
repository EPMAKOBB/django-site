# Site Redesign Progress Log

## 1. Purpose

This file is the working progress log for the site redesign project.

It exists to record, in a compact form:

- what has been completed;
- what is currently in progress;
- what is blocked;
- what has been dropped or postponed;
- which decisions have already been made;
- what should happen next.

This file is not a replacement for the master plan or the stage-level working specs.

Related documents:

- [site_redesign_master_plan.md](D:/FS/django-site/docs/site_redesign_master_plan.md)
- [site_redesign_stage_1_2_foundation_plan.md](D:/FS/django-site/docs/site_redesign_stage_1_2_foundation_plan.md)

## 2. Logging Rules

- Keep entries short and factual.
- Log only meaningful changes, decisions, blockers, or completed tasks.
- Do not rewrite history; add new dated entries instead.
- If a decision changes, record the new decision explicitly.
- If something failed, record the failure and the reason.
- If something is postponed, state whether it is temporary or indefinite.

## 3. Entry Template

Use this structure for each update:

```md
## YYYY-MM-DD

### Done
- ...

### In Progress
- ...

### Blocked
- ...

### Dropped / Postponed
- ...

### Decisions
- ...

### Next
- ...
```

## 4. Current Log

## 2026-04-04

### Done
- Created the redesign master roadmap.
- Created the Stage 1-2 working plan for audit and foundation extraction.
- Confirmed the main redesign direction will be based on `/home-v2/`.
- Confirmed that ASCII art is homepage-only.
- Confirmed that light theme support is mandatory.
- Confirmed the redesign priority order: foundation styles, homepage, subject page, solver, training mode, dashboard.
- Confirmed that backend logic should change minimally and that routes and SEO URLs should remain stable.

### In Progress
- Stage 1-2 execution: current UI audit and `/home-v2/` decomposition.

### Blocked
- None recorded yet.

### Dropped / Postponed
- Full redesign of lower-priority screens until the shared foundation is defined.

### Decisions
- The redesign project will be documented using separate document roles:
- `master plan` for the full roadmap;
- `stage plan` for active-phase specs;
- `progress log` for compact execution tracking.
- The master plan is maintained in English as the canonical planning document.

### Next
- Audit the current homepage and related shared UI patterns.
- Decompose `/home-v2/` into shared primitives and homepage-only effects.
- Define the first draft of design tokens, component inventory, and layout rules.

## 2026-04-04

### Done
- Audited the current shared site shell in `templates/base.html`.
- Confirmed that the current shell still depends on the old global cyber styling stack.
- Audited the current homepage structure and its partial-based content blocks.
- Audited key subject-page templates and the dashboard base template.
- Audited the current global CSS/theme files and confirmed that the old neon/cyber style is deeply wired into the base template.
- Added the first concrete audit findings to the Stage 1-2 working document.
- Added the first `/home-v2/` decomposition snapshot: shared patterns vs homepage-only effects.

### In Progress
- Converting audit findings into a concrete shared foundation proposal.

### Blocked
- None recorded yet.

### Dropped / Postponed
- Full dashboard redesign until the shared foundation is defined and validated on homepage and subject page.

### Decisions
- The current redesign should replace the old shared cyber shell rather than attempt to soften it incrementally.
- `/home-v2/` will be used as a style source and system reference, not copied into production wholesale.
- Mono-heavy typography should not remain the default across the full site.
- ASCII art remains isolated to the homepage.

### Next
- Write the first explicit screen inventory.
- Write the first explicit shared pattern inventory.
- Draft the first token groups and base component list from `/home-v2/`.
- Define the homepage replacement strategy on top of the new shared foundation.

## 2026-04-04

### Done
- Added the first screen inventory to the Stage 1-2 working document.
- Added the first shared pattern inventory to the Stage 1-2 working document.
- Added the first homepage replacement strategy.
- Added the first foundation token draft.
- Added the first typography proposal.
- Added the first canonical shared component set.
- Added the first base layout-rule draft.

### In Progress
- Converting the Stage 1-2 working document from audit mode into implementation-ready guidance.

### Blocked
- None recorded yet.

### Dropped / Postponed
- Final token values until implementation begins and visual comparison in the real shared shell is possible.

### Decisions
- The homepage replacement will be done via shared foundation extraction first, not by promoting `home_v2.html` directly to the production homepage.
- The redesign now has an initial canonical component inventory.
- The redesign now has an initial semantic token structure for dark and light modes.

### Next
- Turn the foundation proposal into an implementation sequence for `base.html`, shared CSS, and homepage migration.
- Decide where the new shared styles will live in the static CSS architecture.
- Start replacing the old shared shell with the new foundation layer.

## 2026-04-04

### Done
- Started implementation of the new shared foundation layer.
- Added `static/css/site-foundation.css` as the new global style entry point.
- Added `static/js/site-theme.js` as the new shared theme-toggle behavior.
- Added `static/js/site-main.js` as the new shared behavior bundle without the old typewriter/theme-preview logic.
- Replaced the old shared shell in `templates/base.html`.
- Replaced the old shared shell in `templates/base_solver.html`.
- Removed the old global shell dependency on `main.css`, `cyber.css`, and `theme.css` for the primary base templates.
- Removed the old global matrix/typewriter/theme-preview shell behavior from the active entry points.
- Verified the project with `python manage.py check`.

### In Progress
- Stabilizing the new foundation layer so existing pages remain usable while the homepage and subject page are migrated.

### Blocked
- None recorded yet.

### Dropped / Postponed
- Direct promotion of `home_v2.html` to production without extraction.

### Decisions
- The old design is now being replaced from the shared shell downward, not page-by-page on top of the old cyber base.
- New global styles are entering through a dedicated foundation stylesheet instead of patching the old CSS stack.
- Old preview-theme and typewriter shell behavior are no longer part of the active redesign direction.

### Next
- Review the production homepage and subject page under the new shell.
- Patch missing shared component styles exposed by the shell replacement.
- Begin homepage migration onto the new foundation layer.

## 2026-04-06

### Done
- Replaced the split login/signup UI with one shared auth page.
- Kept both `/accounts/login/` and `/accounts/signup/` routes alive while routing them to the same shared view.
- Added a new shared auth template at `accounts/templates/accounts/auth.html`.
- Added foundation styles for the shared auth layout.
- Kept post-login and post-signup redirects safe via host-checked `next` handling.
- Verified the project with `python manage.py check`.

### In Progress
- Converting more isolated legacy screens into shared components on top of the new foundation layer.

### Blocked
- None recorded yet.

### Dropped / Postponed
- Maintaining separate standalone auth page designs for login and signup.

### Decisions
- Login and signup now share one entry page with two explicit blocks.
- Existing auth URLs remain stable even though the UX is unified.

### Next
- Review the new auth page in the browser flow and adjust copy/layout if needed.
- Continue migrating homepage structure onto the new foundation.

## 2026-04-06

### Done
- Added page-level asset hooks to the shared base template.
- Replaced the old partial-based homepage structure in `templates/home.html`.
- Added a new homepage-specific stylesheet at `static/css/homepage.css`.
- Rebuilt the homepage around the new production composition:
- hero;
- homepage-only ASCII background scene;
- self-study card;
- teacher-led application card;
- how-it-works section;
- expanded about section;
- separate socials block;
- testimonials block;
- final CTA block.
- Preserved the existing `active_exams` and application form flows inside the new homepage structure.
- Reused the homepage-only ASCII scene behavior from the existing `/home-v2/` implementation.
- Verified the project with `python manage.py check`.

### In Progress
- Reviewing the new homepage as the first production consumer of the new design system.

### Blocked
- None recorded yet.

### Dropped / Postponed
- Keeping the old homepage partial assembly as the active production structure.

### Decisions
- The production homepage now follows the `/home-v2/` composition direction instead of the old partial-driven landing layout.
- Homepage-specific spectacle remains isolated to homepage-only assets and does not re-enter the shared shell.
- Social links are currently implemented as a separate homepage block and can be merged into `About` later if needed.

### Next
- Review the homepage in the browser and refine copy, spacing, and light-theme behavior.
- Patch any shared component gaps exposed by the new homepage.
- Move from homepage polishing into subject-page redesign.
