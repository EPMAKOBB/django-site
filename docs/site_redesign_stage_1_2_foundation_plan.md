# Site Redesign Stage 1-2 Plan: Audit and Foundation Extraction

## 1. Purpose

This document is the working specification for the first active redesign phase.

It covers:

- auditing the current site interface;
- decomposing `/home-v2/` into reusable design primitives;
- defining the foundation layer of the new design system;
- preparing the project for implementation of shared styles and key screens.

This document is subordinate to [site_redesign_master_plan.md](D:/FS/django-site/docs/site_redesign_master_plan.md) and should be used as the active working file for the first redesign wave.

## 2. Scope of This Stage

This stage does not redesign the whole product yet.

It focuses on:

- understanding the current UI landscape;
- identifying what must change visually;
- extracting the reusable system from `/home-v2/`;
- defining the first shared style foundation for the site.

This stage does not include:

- full implementation of all redesigned pages;
- deep backend restructuring;
- final dashboard restructuring;
- broad URL or SEO changes.

## 3. Strategic Outcome

By the end of Stage 1-2, the project should have:

- a map of current screens and repeated UI patterns;
- a clear list of visual and UX problems in the current interface;
- a documented decomposition of `/home-v2/`;
- a first version of design tokens;
- a first version of the reusable component inventory;
- a technical direction for implementing the foundation layer.

## 4. Working Assumptions

- `/home-v2/` is the visual source of truth for the redesign direction.
- ASCII art remains homepage-only and is not part of the shared system.
- The redesign must support both dark and light themes from the start.
- Existing backend logic, routes, and SEO URLs should remain largely stable.
- Application forms remain structurally intact.
- Shared UI foundations must be usable across homepage, subject page, solver, training mode, and dashboard.

## 5. Stage Structure

This stage is split into two operational tracks:

### Track A. Current Site Audit

Understand the current product surface and identify what exists today.

### Track B. `/home-v2/` Foundation Extraction

Turn the draft homepage into a reusable visual system for the wider site.

## 6. Track A: Current Site Audit

## A1. Build the Screen Inventory

Goal:
Create a practical list of the screens that matter for the redesign.

Tasks:

- identify all key user-facing pages;
- group them by priority and product role;
- distinguish marketing pages from working product pages;
- identify which pages are likely to reuse the same visual patterns.

Expected output:

- homepage;
- subject page;
- solver;
- training mode interface;
- dashboard;
- shared support pages where relevant.

Deliverable:

- screen inventory table.

## A2. Map Shared Layout and UI Patterns

Goal:
Find the recurring interface structures already present in the site.

Tasks:

- identify current header and footer behavior;
- identify common containers and section patterns;
- identify current card, button, link, and form patterns;
- identify repeated content structures such as lists, tabs, progress blocks, and dashboard blocks.

Deliverable:

- shared pattern inventory.

## A3. Identify Current UI Problems

Goal:
Document what is visually or structurally wrong with the current interface.

Problem categories:

- overly saturated or harsh colors;
- inconsistent spacing;
- weak visual hierarchy;
- overloaded blocks;
- inconsistent typography;
- unclear call-to-action hierarchy;
- poor dark/light balance;
- duplicated or conflicting visual patterns;
- pages that feel disconnected from each other.

Deliverable:

- current UI problem list, grouped by severity and frequency.

## A4. Define Priority by User Value

Goal:
Make sure redesign effort follows the most important screens first.

Priority order currently assumed:

1. shared foundation styles;
2. homepage;
3. subject page;
4. solver;
5. training mode entity;
6. dashboard.

Deliverable:

- approved redesign order for implementation.

## A5. Document Constraints Per Screen

Goal:
Record where redesign means pure restyling and where structural changes are allowed.

For each key screen, define:

- what must remain unchanged;
- what may be visually reworked;
- what may be structurally reworked;
- whether data shape changes are allowed;
- whether UX flow changes are allowed.

Deliverable:

- screen-level constraint matrix.

## 7. Track B: `/home-v2/` Foundation Extraction

## B1. Separate Shared Patterns from Homepage-Only Effects

Goal:
Prevent decorative homepage experiments from leaking into the full-site system.

Shared candidates:

- color palette direction;
- typography direction;
- buttons;
- form fields;
- cards and content surfaces;
- header;
- footer;
- spacing rhythm;
- border and radius language.

Homepage-only candidates:

- ASCII hero animation;
- highly atmospheric hero treatment;
- oversized landing-specific hero composition.

Deliverable:

- shared-vs-homepage-only decision list.

## B2. Extract Design Tokens

Goal:
Turn `/home-v2/` styling into reusable design variables.

Token groups:

- background tokens;
- surface tokens;
- text tokens;
- border tokens;
- accent tokens;
- shadow tokens;
- radius tokens;
- spacing tokens;
- typography tokens;
- control sizing tokens.

Deliverable:

- first draft of design tokens for both dark and light themes.

## B3. Extract Typography Rules

Goal:
Define a consistent text system instead of page-local styling.

Typography decisions should cover:

- primary UI font family;
- mono font usage rules;
- heading scale;
- body text scale;
- label and helper text scale;
- uppercase usage rules;
- line-height rules;
- text contrast rules across both themes.

Deliverable:

- typography specification.

## B4. Extract Core Components

Goal:
Turn visible patterns from `/home-v2/` into reusable site components.

Core component candidates:

- site header;
- site footer;
- primary button;
- secondary button;
- ghost button;
- text link style;
- input field;
- textarea;
- select field;
- checkbox/radio pattern;
- card surface;
- section wrapper;
- container;
- theme toggle;
- form action row.

Deliverable:

- reusable component inventory with intended scope.

## B5. Extract Layout Rules

Goal:
Define how pages should be composed using the new system.

Layout decisions should cover:

- page width and container rules;
- section padding rhythm;
- spacing between major blocks;
- card stacking behavior;
- mobile behavior;
- desktop behavior;
- alignment rules for forms and content sections.

Deliverable:

- base layout rules.

## B6. Define Theme Behavior

Goal:
Decide how dark and light modes behave at a system level.

Questions to resolve:

- is the theme user-controlled, system-controlled, or both;
- what is the default theme;
- which colors invert and which do not;
- how accents behave in light mode;
- how focus and hover states adapt across themes.

Deliverable:

- theme behavior specification.

## 8. Combined Deliverables for Stage 1-2

By the end of this stage, the following artifacts should exist:

- screen inventory;
- shared pattern inventory;
- UI problem list;
- screen-level constraint matrix;
- shared-vs-homepage-only decision list;
- first design token draft;
- typography specification;
- reusable component inventory;
- base layout rules;
- theme behavior specification;
- implementation direction for the foundation layer.

## 9. Decision Points That Must Be Explicitly Approved

The following decisions should be written down instead of left implicit:

- final visual direction inherited from `/home-v2/`;
- final color philosophy for both themes;
- final typography direction;
- whether theme toggle is global or limited;
- which components become canonical shared components;
- which homepage effects remain one-off;
- where structural UX changes are allowed beyond simple restyling.

## 10. Recommended Documentation Format

To keep this stage actionable, each artifact should use a compact format.

Recommended formats:

- screen inventory: table;
- pattern inventory: grouped bullet list;
- UI problems: severity-ranked list;
- token draft: grouped variables;
- typography spec: rules + type scale;
- component inventory: name, purpose, scope, notes;
- constraints matrix: page-by-page table.

## 11. Implementation Readiness Criteria

Stage 1-2 is complete only when:

- the team can name the shared design primitives clearly;
- the difference between shared UI and homepage-only effects is explicit;
- both dark and light themes have defined token logic;
- the first implementation step for the foundation layer is obvious;
- homepage and subject-page redesign can begin without rethinking the whole system again.

## 12. Next Document After This Stage

Once this stage is complete, the next detailed document should cover Stage 5-6 implementation planning:

- CSS architecture;
- template and partial structure;
- token implementation;
- shared component rollout;
- header/footer migration;
- theme system integration.

## 13. Current Audit Snapshot

Status:
Initial audit pass completed on 2026-04-04.

This section records the first concrete findings from the repository review.

### 13.1 Current Shared Shell Findings

Observed shared shell:

- the current site shell is centered on `templates/base.html`;
- the shared shell loads `static/css/main.css`, `static/css/cyber.css`, and `static/css/theme.css`;
- the global shell still includes a decorative matrix background layer;
- the current header uses a mono-heavy cyber presentation;
- the current shell includes a temporary theme preview control, not a final theme system.

Problems identified:

- the existing visual foundation is already globally coupled into the base template;
- the current design language is strongly neon/cyber and too aggressive for the new direction;
- typography is too mono-dominant for broad site usage;
- decorative effects are part of the global shell instead of being page-specific;
- the current theme mechanism is a preview tool, not a production-ready light/dark system;
- some existing text content appears to have encoding issues and should be treated as a cleanup item during redesign.

Conclusion:

- the redesign should not be implemented as incremental tweaks to the old cyber layer;
- a new shared foundation layer should be created and then adopted by the base template.

### 13.2 Current Homepage Inventory

The current production homepage is structurally simple and composed from partials:

- `home.html`
- `partials/exams_intro.html`
- `partials/enroll.html`
- `partials/aboutus.html`
- `partials/testimonials.html`
- `partials/cta.html`

Current homepage content structure:

- hero/title introduction;
- active exams entry block;
- application/enrollment form block;
- about/team block;
- testimonials block;
- final CTA block.

Homepage problems identified:

- block language is visually inconsistent with the calmer direction of `/home-v2/`;
- CTA hierarchy is fragmented across multiple sections;
- the visual system feels assembled from old reusable cyber blocks instead of a deliberate homepage narrative;
- the enrollment block is functionally useful but visually heavy;
- there is no strong single homepage composition comparable to `/home-v2/`.

Conclusion:

- the current homepage content inventory is still useful;
- the visual and structural presentation should be rebuilt rather than lightly restyled.

### 13.3 Subject Page Snapshot

Observed key templates:

- `templates/exams/detail.html`
- `templates/exams/type_detail.html`

Subject-page characteristics:

- relies on the global shared shell from `base.html`;
- mixes skeleton loading, progress display, cards, chips, and dynamic content insertion;
- depends on existing shared utility and card/button styles from the old design system.

Subject-page problems identified:

- the page inherits the old aggressive global visual system automatically;
- the information hierarchy is functional but not yet visually calm or structured enough;
- current reusable elements are too tightly tied to the outgoing cyber theme.

Conclusion:

- the subject page should be one of the first production consumers of the new foundation layer after the homepage.

### 13.4 Dashboard Snapshot

Observed dashboard base:

- `accounts/templates/accounts/dashboard/base.html`

Dashboard characteristics:

- tab-based navigation;
- role-dependent sections;
- many child templates and a large product surface;
- heavy dependence on current global classes and shared styling.

Conclusion:

- dashboard redesign should not be the first implementation target;
- it should wait until the new shared foundation is proven on homepage and subject page.

## 14. `/home-v2/` Decomposition Snapshot

Status:
Initial decomposition pass completed on 2026-04-04.

### 14.1 Shared vs Homepage-Only Separation

Shared candidates from `/home-v2/`:

- calmer dark palette direction;
- explicit light-theme counterpart;
- refined surface hierarchy;
- less aggressive border treatment;
- button styling;
- form-field styling;
- card and panel styling;
- header layout pattern;
- footer layout pattern;
- cleaner spacing rhythm;
- mixed UI typography with separate mono accent usage.

Homepage-only candidates from `/home-v2/`:

- ASCII canvas scene;
- atmospheric hero overlays;
- oversized center hero composition;
- homepage-specific visual drama around the logo/title mark.

Decision:

- `/home-v2/` should be treated as a style source, not as a page to be copied whole into production.

### 14.2 First Token Categories to Extract

The first token draft should be extracted in these groups:

- app background;
- elevated surface backgrounds;
- border strength tiers;
- primary text;
- muted text;
- primary accent;
- hover/focus accent;
- shadows;
- radii;
- container width;
- control heights;
- UI font family;
- mono accent font family.

### 14.3 First Shared Component Candidates

The following patterns from `/home-v2/` should become reusable shared components:

- global site header;
- brand block;
- primary CTA button;
- secondary/quiet button;
- text-action button style;
- shared form field styles;
- shared checkbox group styling;
- shared card/panel surface;
- standard content section wrapper;
- footer block;
- theme toggle behavior and visual treatment.

### 14.4 Homepage-Only Components

The following should remain exclusive to the homepage:

- ASCII hero scene wrapper;
- hero intro composition;
- homepage atmospheric visual layers;
- homepage-specific staging around top-level CTA blocks.

## 15. Foundation Direction: First Decisions

These decisions are now stable enough to treat as working assumptions:

- the old cyber/matrix layer will not remain part of the new shared identity;
- the new global system should be based on the calmer palette and surface logic of `/home-v2/`;
- the shared site typography should move away from mono-only presentation;
- mono should remain available as a supporting accent, not as the default voice of the entire product;
- the light theme must be designed as a full first-class system;
- homepage-only spectacle must stay isolated from product-wide shared styles.

## 16. Immediate Next Work

The next execution step inside Stage 1-2 is:

- write the first explicit screen inventory;
- write the first explicit shared pattern inventory;
- write the first token draft based on `/home-v2/`;
- write the first component inventory and layout rules;
- prepare the implementation strategy for replacing the old homepage shell.

## 17. First Screen Inventory

This is the first practical screen inventory for the redesign program.

### 17.1 Wave 1 Screens

These are the first production targets after the shared foundation is defined.

| Screen | Current Template Base | Role | Redesign Depth |
| --- | --- | --- | --- |
| Homepage | `templates/home.html` + partials | Acquisition and conversion | High |
| Subject page | `templates/exams/detail.html` + `templates/exams/_public_blocks.html` | Product entry and progression | High |

### 17.2 Wave 2 Screens

| Screen | Current Template Base | Role | Redesign Depth |
| --- | --- | --- | --- |
| Solver | `accounts/templates/accounts/dashboard/variant_attempt_solver.html` | Core working product interface | High |
| Training mode entity | Not finalized yet | New learning workflow surface | High |

### 17.3 Wave 3 Screens

| Screen | Current Template Base | Role | Redesign Depth |
| --- | --- | --- | --- |
| Dashboard shell | `accounts/templates/accounts/dashboard/base.html` | Product navigation shell | Medium to High |
| Dashboard sections | multiple dashboard child templates | Product management and progress | Medium to High |

### 17.4 Shared Shell Screens

These are not standalone redesign targets but shared dependencies across the site.

| Shared Layer | Current Base | Role |
| --- | --- | --- |
| Global base template | `templates/base.html` | Shared shell |
| Global stylesheet layer | `static/css/main.css`, `static/css/cyber.css`, `static/css/theme.css` | Shared styling |
| Theme behavior | `static/js/theme.js` | Temporary theme preview logic |

## 18. First Shared Pattern Inventory

This inventory captures the main reusable UI patterns currently present in the project.

### 18.1 Current Shared Shell Patterns

- sticky header;
- brand block with mark and text;
- container layout;
- generic button style;
- section wrapper;
- card/block surfaces;
- tab navigation in dashboard contexts;
- mixed utility-class styling;
- form field styling;
- variant and task interaction blocks.

### 18.2 Current Product Patterns

- exam CTA buttons;
- progress bars;
- progress chips/tags;
- type cards;
- task cards;
- dashboard tabs;
- dashboard content panels;
- role-based content sections;
- alert/warning messages;
- skeleton loading blocks.

### 18.3 Patterns That Should Be Rebuilt on the New Foundation

- global header;
- global footer;
- all primary and secondary buttons;
- card and panel surfaces;
- form controls;
- section wrappers;
- content containers;
- dashboard tabs;
- progress indicators;
- CTA group layouts.

### 18.4 Patterns That Should Be Isolated or Removed

- global matrix background;
- global neon cyber effects;
- mono-as-default typography voice;
- temporary theme preview control in the header;
- overly decorative global accent treatments inherited from the old style system.

## 19. Homepage Replacement Strategy

The homepage should be replaced through controlled migration, not by switching `home.html` directly to the current draft file.

### 19.1 Core Strategy

The migration path should be:

1. extract shared foundations from `/home-v2/`;
2. implement those foundations in the real global shell;
3. rebuild homepage sections using shared production components;
4. keep homepage-only hero effects isolated to the homepage template and homepage-specific assets.

### 19.2 Content Strategy

The existing homepage already contains useful content blocks that should be reused or reshaped:

- exam discovery CTA;
- teacher-led application form;
- about/team block;
- testimonials;
- final CTA.

The new homepage should therefore combine:

- the calmer visual language and stronger composition of `/home-v2/`;
- the functional content inventory already present in the production homepage.

### 19.3 Migration Principle

The new homepage should not be:

- a copy of the current draft file;
- a partial restyle of the old homepage blocks;
- a one-off isolated design that cannot be reused by the subject page.

The new homepage should be:

- the first real production consumer of the new shared foundation;
- the reference page for future redesign work;
- the only page that carries the ASCII “wow effect”.

## 20. Immediate Foundation Deliverables to Produce Next

The next concrete outputs should be created in this order:

1. first token draft;
2. first typography proposal;
3. first shared component inventory;
4. first layout rules;
5. implementation migration outline for `base.html` and homepage replacement.

## 21. First Foundation Token Draft

Status:
Initial working draft.

This is not yet the final token table. It is the first structured extraction from `/home-v2/` to guide implementation.

### 21.1 Background and Surface Tokens

Core direction:

- dark backgrounds should be deep blue-slate rather than green-black;
- surfaces should feel quiet, layered, and restrained;
- light theme surfaces should feel soft and architectural rather than sterile white.

Proposed token groups:

- `--color-bg-app`
- `--color-bg-app-soft`
- `--color-surface-1`
- `--color-surface-2`
- `--color-surface-2-hover`
- `--color-surface-overlay`

### 21.2 Border Tokens

Core direction:

- borders should become more structural and less glowing;
- most borders should support hierarchy rather than demand attention.

Proposed token groups:

- `--color-border-subtle`
- `--color-border-strong`
- `--color-border-focus`

### 21.3 Text Tokens

Core direction:

- primary text should remain high-contrast but less icy and synthetic than the current system;
- secondary text should be calmer and more editorial.

Proposed token groups:

- `--color-text-primary`
- `--color-text-secondary`
- `--color-text-muted`
- `--color-text-on-accent`

### 21.4 Accent Tokens

Core direction:

- move from neon accent behavior to controlled cool-blue emphasis;
- keep accent usage functional: CTA, focus, state emphasis, selected controls.

Proposed token groups:

- `--color-accent-primary`
- `--color-accent-primary-hover`
- `--color-accent-soft`
- `--color-focus-ring`

### 21.5 Shadow Tokens

Core direction:

- shadows should suggest elevation and atmosphere, not glow;
- homepage-only atmospheric glow should not become a global token rule.

Proposed token groups:

- `--shadow-panel`
- `--shadow-elevated`
- `--shadow-overlay`

### 21.6 Radius Tokens

Proposed token groups:

- `--radius-sm`
- `--radius-md`
- `--radius-lg`
- `--radius-pill`

### 21.7 Layout Tokens

Proposed token groups:

- `--container-max`
- `--section-space-y`
- `--section-space-y-compact`
- `--grid-gap-sm`
- `--grid-gap-md`
- `--grid-gap-lg`

### 21.8 Control Tokens

Proposed token groups:

- `--control-height-sm`
- `--control-height-md`
- `--control-height-lg`
- `--control-padding-x`

### 21.9 Theme Strategy

The first token draft should be implemented in parallel for:

- dark mode;
- light mode.

Token behavior should be semantic, not page-local.

This means:

- token names should describe role, not literal color;
- theme switching should remap values, not swap component classes page by page.

## 22. First Typography Proposal

Status:
Initial working direction.

### 22.1 Typography Direction

The new site should not use mono as the default voice.

Working rule:

- UI and body text should use a clean humanist or neutral sans family;
- mono should remain available for accents, technical hints, marks, small labels, and selective identity cues.

### 22.2 Typography Roles

The system should define:

- display title;
- page title;
- section title;
- card title;
- body text;
- secondary body text;
- label text;
- helper text;
- mono accent text.

### 22.3 Typography Behavior

Working principles:

- avoid all-caps as the default rule across the interface;
- use uppercase only for small metadata, chips, and controlled accent moments;
- preserve strong readability in both themes;
- reduce the current “terminal interface” feeling outside special contexts.

## 23. First Shared Component Set

Status:
Initial canonical component list.

These should become the first reusable UI layer.

### 23.1 Global Shell Components

- site header;
- brand mark;
- top-level navigation area;
- account CTA entry;
- global footer;
- theme toggle.

### 23.2 Action Components

- primary button;
- secondary button;
- quiet button;
- text link style;
- icon button;
- pill/chip button where needed.

### 23.3 Form Components

- text input;
- textarea;
- select;
- checkbox;
- checkbox group;
- inline field row;
- form submit row;
- validation/error state.

### 23.4 Surface Components

- content card;
- elevated panel;
- section wrapper;
- content container;
- split CTA panel for homepage use;
- alert/warning panel.

### 23.5 Product Components

- progress bar;
- progress chip/tag;
- tab navigation;
- skeleton placeholder;
- task card base;
- type card base.

## 24. First Layout Rules

Status:
Initial working direction.

### 24.1 Page Composition

Working rules:

- pages should be built from consistent vertical sections;
- section spacing should be calmer and more generous than the current site;
- the homepage may be more atmospheric, but internal pages should be structurally restrained.

### 24.2 Container Behavior

Working rules:

- standard content should sit within one shared max-width container;
- dense product interfaces may use wider layout rules, but should still inherit the same spacing language;
- dashboard and solver may later need dedicated wide-layout variants.

### 24.3 Section Hierarchy

Working rules:

- each page should have a clear hero or page-intro zone;
- each major block should sit on a clear surface or spacing boundary;
- CTA blocks should be intentional, not scattered as repeated bright buttons.

### 24.4 Mobile Behavior

Working rules:

- header controls must remain usable on narrow screens;
- forms should collapse into vertical flow cleanly;
- cards should stack without becoming visually noisy;
- dark and light themes must both remain readable on mobile.
