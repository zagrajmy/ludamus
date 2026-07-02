# 6. HTMX adoption (frontend)

**Status:** 🟡 in progress
**Tracked in TODO:** Epic "Migrate to HTMX" (ticket 10)

## Goal

Move interactive panel and form flows from full-page POST/redirect cycles to
HTMX partial swaps, so editing, list mutations and multi-step wizards update
in place instead of reloading the page.

## Why

The panel is form-heavy (CFP, proposals, venues, time slots, tracks,
facilitators). Full-page reloads on every mutation are the main UX cost called
out in CLAUDE.md ("are we asking for needless clicks?"). HTMX lets a list row,
a form, or a wizard step re-render server-side without a client framework.

## Current state (2026-05-24)

- **Bootstrap → Tailwind is effectively done**: zero `bootstrap` references in
  `src/ludamus/templates/`. Styling is Tailwind 4 built through Vite in
  `src/ludamus/client/` (`@tailwindcss/vite`, `tailwindcss@4.1.16`,
  `@tailwindcss/typography`, `prettier-plugin-tailwindcss`). Treat the
  Bootstrap removal as a completed refactor, not an in-flight one.
- **HTMX is partially adopted**: a number of templates already use `hx-*`
  attributes. The TypeScript surface in `client/src/` (`tabs.ts`, `modal.ts`,
  `confirm.ts`, `timetable.ts`, `encounter-form.ts`, `django-hmr.ts`) backs the
  interactive bits; `fallow` runs TypeScript analysis in CI.

There is no per-page tracking of which flows are HTMX-driven vs full reload —
that inventory is the missing artifact.

## Next step

1. Inventory the panel: list each mutating flow and mark HTMX vs full-page
   reload (start with the highest-traffic list pages — proposals, venues,
   tracks).
2. Convert one flow end to end as the pattern reference, with the partial
   template + `hx-target`/`hx-swap` convention documented. Run it past the
   **hector** skill (HTMX reviewer) and **tessa**/**lillend** (Tailwind /
   frontend review) before generalising.
3. Capture before/after screenshots via agent-browser for the PR, per CLAUDE.md.

## Definition of done

- A documented HTMX partial-swap convention exists and the high-traffic panel
  list/edit flows follow it.
- Destructive actions use the existing styled `data-confirm` dialog
  (`confirm.ts`) rather than full-page confirm screens.

## Notes

- Frontend config files (`package.json`, `tsconfig.json`, `vite.config.ts`,
  Tailwind config) are the **only** config files exempt from the
  "no config changes without approval" rule (per CLAUDE.md and commit
  `1683a8a4`). Non-TypeScript config still needs per-case approval.
