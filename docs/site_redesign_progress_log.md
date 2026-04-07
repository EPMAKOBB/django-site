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

## 2026-04-06

### Done
- Removed the obsolete homepage partial assembly files that were no longer part of the live homepage path.
- Confirmed that the production homepage no longer depends on the old `partials/exams_intro`, `partials/enroll`, `partials/aboutus`, `partials/testimonials`, or `partials/cta` templates.
- Verified the project with `python manage.py check` after the cleanup.

### In Progress
- Homepage cleanup and stabilization after the structural migration.

### Blocked
- None recorded yet.

### Dropped / Postponed
- Broader deletion of old shell assets during this homepage-only cleanup pass, because some legacy files are still indirectly referenced by tests and documentation.

### Decisions
- Homepage cleanup is being handled conservatively: remove dead live-template files first, then do broader legacy asset cleanup in a dedicated pass.

### Next
- Review whether `templates/partials/about_fractal.html` still has any product value or should also be removed later.
- Continue with homepage polish and then move to the subject page.

## 2026-04-07

### Done
- Approved the planned information architecture for the subject page redesign.
- Recorded the agreed subject-page structure in the Stage 1-2 working document.

### In Progress
- Subject-page planning before implementation.

### Blocked
- None recorded yet.

### Dropped / Postponed
- Implementation of the future support/motivation layer on the subject page for now.

### Decisions
- The subject page will be structured in four layers:
- top summary;
- what to do next;
- task types;
- reserved future support area.
- The reserved future support area will stay unimplemented for now, but the architecture must leave room for it.
- Priority for this subject-page redesign plan is medium.

### Next
- Translate the approved subject-page structure into template-level implementation planning.
- Define the data and fallback logic for "continue from the last active point".

## 2026-04-07

### Done
- Started subject-page implementation on top of the approved 4-layer structure.
- Replaced the old thin exam shell in `templates/exams/detail.html` with a new page-level summary layout.
- Rebuilt `templates/exams/_public_blocks.html` around:
- `what to do next`;
- task types;
- reserved future support slot.
- Added a dedicated page stylesheet at `static/css/exam-detail.css`.
- Added a dedicated page script at `static/js/exam-detail.js`.
- Implemented client-side summary enrichment using existing progress data:
- overall progress;
- current forecast placeholder based on current type coverage;
- strongest types;
- weakest types;
- next best action;
- resume-from-last-active fallback using local browser storage.
- Kept the existing backend endpoints and personal mock POST flow intact.

### In Progress
- First visible subject-page milestone review.

### Blocked
- No dedicated public training-mode page exists yet, so the training action remains a reserved coming-soon state.

### Dropped / Postponed
- The future support layer remains unimplemented for now.

### Decisions
- Subject-page redesign is being delivered in reviewable UI milestones.
- "Continue from the last active point" will initially use browser-side persistence plus a weakest-type fallback, avoiding backend changes in this phase.

### Next
- Review the first visible subject-page rebuild in the browser.
- Refine copy, spacing, and action hierarchy based on feedback.
- Only after approval, move to the next subject-page refinement pass.

## 2026-04-07

### Done
- Simplified the subject-page action block after UI review.
- Reduced `What to do next` from four competing actions to two core actions:
- personal mock exam;
- personal training mode placeholder.
- Removed the unused resume / next-best-action subject-page client logic so the implementation matches the approved UI.

### In Progress
- Subject-page first milestone is now in a cleaned and stabilized state.

### Blocked
- No dedicated public training-mode page exists yet, so the second action remains a placeholder.

### Dropped / Postponed
- Resume and next-best-action CTAs are postponed from the visible subject-page action area for now.

### Decisions
- The subject-page action block should stay minimal and low-friction in the current phase.
- Secondary guidance should not compete with the two core learning modes on this screen.

### Next
- Continue later with subject-page polish and then move toward the real training-mode implementation.
