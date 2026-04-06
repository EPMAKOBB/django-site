# Site Redesign Master Plan: Outline

## 1. Purpose of This Document

This document is the top-level roadmap for the full site redesign. Its purpose is to:

- preserve the overall redesign direction;
- keep the work phase-based instead of changing isolated pages at random;
- validate each new task against the larger project architecture;
- gradually expand this outline into detailed implementation instructions.

The primary visual source for the redesign is `/home-v2/`.

Core principle: first build the new visual system, then migrate the key screens and related entities onto that system in a controlled order.

## 2. Project Goals

- Move away from the current harsh, overly saturated visual language.
- Build a calmer, more cohesive, and more modern site style.
- Make the light theme a first-class experience, not an afterthought.
- Use `/home-v2/` as the foundation of the new design system.
- Preserve the existing backend logic, URL structure, and SEO surface with minimal change.
- Update not only the visual layer, but also selected content blocks and page structures.

## 3. Project Constraints

- Backend logic should be changed as little as possible.
- Routes and SEO URLs must remain stable.
- Application forms must be preserved.
- ASCII art is used only on the homepage.
- The visual system must work across the full site, not only for a landing page.
- The dashboard data structure may change in limited ways, but without a deep product-level rewrite.

## 4. Delivery Priority

### Wave 1

- Base styles and design system foundation.
- Homepage.
- Subject page.

### Wave 2

- Solver.
- New training-mode entity and interface.

### Wave 3

- User dashboard.

## 5. End-to-End Project Route

## Stage 0. Lock the Project Frame

Goal:
Define exactly what is being redesigned, in what order, and under which constraints.

Deliverables:

- approved list of Wave 1, Wave 2, and Wave 3 screens;
- approved list of project constraints;
- explicit confirmation that `/home-v2/` is the visual starting point.

## Stage 1. Audit the Current Interface

Goal:
Break the current site down into actual screens, patterns, and problem areas.

What happens here:

- collect the list of key pages;
- identify recurring UI elements;
- record the visual problems of the current site;
- record which blocks feel overloaded, outdated, or confusing;
- compare the current homepage with `/home-v2/`.

Deliverables:

- screen map;
- list of reusable components;
- list of visual and UX problems;
- list of patterns and ideas to carry over from `/home-v2/`.

## Stage 2. Decompose `/home-v2/` into a System

Goal:
Turn the experimental page into a set of reusable primitives for the whole site.

What happens here:

- separate homepage-only decorative elements from reusable interface elements;
- extract tokens for color, background, text, borders, and shadows;
- extract typography rules;
- extract buttons, fields, cards, containers, and section patterns;
- extract header and footer patterns;
- decide which parts remain homepage-only.

Deliverables:

- design token list;
- base component list;
- homepage-only pattern list;
- first version of the new design system map.

## Stage 3. Design the Dark and Light Themes

Goal:
Design the two-theme system from the start instead of retrofitting the light theme later.

What happens here:

- define the token set for the dark theme;
- define the token set for the light theme;
- validate contrast, readability, and accent-color behavior;
- define component states in both themes.

Deliverables:

- token tables for both themes;
- theme-switching rules;
- constraints for accent-color usage.

## Stage 4. Build the Design System

Goal:
Create a stable UI system that all redesigned pages can rely on.

What happens here:

- define the grid and spacing system;
- define rules for sections, cards, buttons, forms, and links;
- define hover, focus, disabled, and error states;
- define base layout patterns;
- define desktop and mobile behavior.

Deliverables:

- mini design system;
- implementation-facing UI spec;
- list of required components.

## Stage 5. Plan the Technical Integration

Goal:
Define how the new system enters the current Django project without creating chaos.

What happens here:

- define the CSS file structure;
- identify which inline solutions from `/home-v2/` must move into static files;
- define the new base layout;
- define the partials/includes strategy;
- define the page migration strategy.

Deliverables:

- file structure plan;
- technical integration plan;
- list of templates and partials to update.

## Stage 6. Implement the Foundation Layer

Goal:
Ship the shared design foundation before rebuilding individual screens.

What happens here:

- create design tokens;
- create global base styles;
- create base UI components;
- update header and footer;
- add theme switching if it is part of the shared architecture.

Deliverables:

- working foundation for the new style;
- unified global components;
- stable base for page migration.

## Stage 7. Redesign the Homepage

Goal:
Move the homepage onto the new system and make it the reference implementation.

What happens here:

- redesign the homepage structure;
- transfer the strongest ideas from `/home-v2/`;
- keep ASCII art only here;
- create a clearer narrative flow;
- align CTA blocks and trust blocks with the new system.

Deliverables:

- redesigned homepage;
- first production page in the new style;
- reference screen for later migrations.

## Stage 8. Redesign the Subject Page

Goal:
Update the second most important screen after the homepage.

What happens here:

- rebuild the page using the new design system;
- simplify content hierarchy;
- make key actions and progress states easier to understand;
- preserve current URL and backend behavior.

Deliverables:

- redesigned subject page;
- visual and UX consistency with the homepage.

## Stage 9. Redesign Solver and Training Mode

Goal:
Extend the new system into working learning interfaces, not only marketing pages.

What happens here:

- adapt solver to the new components;
- design the interface for the new training-mode entity;
- validate how the new style behaves on more complex interactive screens.

Deliverables:

- consistent style across both marketing and product surfaces;
- base visual model for more complex interfaces.

## Stage 10. Redesign the Dashboard

Goal:
Update the dashboard after the new system has been proven on key screens.

What happens here:

- redesign the dashboard’s visual hierarchy;
- update the key blocks;
- partially revise data structure and layout where needed;
- preserve compatibility with the core product logic.

Deliverables:

- calmer and clearer dashboard;
- reduced visual noise;
- unified interface language across the product.

## Stage 11. Consolidate and Remove Legacy UI

Goal:
After the key pages are migrated, remove duplicates, temporary workarounds, and conflicting old styles.

What happens here:

- remove outdated styles and template leftovers;
- merge repeated rules;
- verify that old harsh themes and component conflicts are gone;
- stabilize the codebase after the redesign.

Deliverables:

- cleaner style and template structure;
- reduced technical debt;
- clearer path for future interface work.

## Stage 12. QA, Polish, and Rollout

Goal:
Validate that the redesign is stable, coherent, and production-ready across the full site.

What happens here:

- test desktop and mobile layouts;
- test both themes;
- test forms, states, and empty screens;
- test performance, especially on the homepage;
- test visual consistency across screens;
- complete the rollout.

Deliverables:

- stable launch of the new visual layer;
- documented final project status;
- clean base for future iterations.

## 6. How to Use This Document

- This file remains the top-level map of the redesign.
- Each stage should later get its own detailed implementation document.
- Every new redesign task should be mapped to one of the stages in this plan.
- If a new idea appears, it should first be added to the plan and only then moved into implementation.

## 7. Next Step

The next working document should focus on Stage 1 and Stage 2:

- auditing the current screens;
- decomposing `/home-v2/` into reusable visual primitives;
- defining the foundation layer of the new style system.
