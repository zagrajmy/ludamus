# PR 634 TODOs

## Completed

- [x] Use one `DateSelection = date | Literal["all"]` through view, mill,
  DTO, and templates.
- [x] Resolve missing or invalid date selection to `"all"`.
- [x] Extract `TimetableService` to `mills/timetable.py`.
- [x] Use one time-slot create modal. Keep the old create endpoint as a
  redirect to `?create=1`, preserving a validated, encoded date.
- [x] Replace enumerated column-count CSS with `--column-count`.
- [x] Use one timetable layout path.
- [x] Fix valid CodeRabbit findings: Auth0 binding/message, keyword-only
  helpers, safe pagination, encoded redirect, tautology removal, and
  accessible session lookup.
- [x] Keep the sidebar icon permanently rotated in Tailwind, matching its
  fixed skinny-left/fat-right orientation.
- [x] Let Tessera buttons spread safe extra attributes. Move trivial `title`,
  ARIA, modal-close, and link attributes onto that path.
- [x] Use Tessera for new modal Assign and Cancel controls.
- [x] Prefer accessible E2E interaction locators. Keep CSS selectors only for
  layout and timetable-grid geometry.
- [x] Migrate remaining menus to `menu_surface`; remove the fallback API.
- [x] Fix the CI panel-height regression.
- [x] Include Oxfmt in the aggregate `mise run format` task.

## CI investigation

- Failed commit: `5f1bc3cd17f613e595e83e7de29de4b6b64bdd3d`
- Run: `30023790464`
- Artifact: `playwright-report` (`8570561132`)
- Failure was deterministic across three attempts: the tab body stopped
  `53px` above the panel bottom.
- Cause: `min-h-full` forced the nested flex child to reserve a full panel
  height after the tab bar had already consumed space.
- Fix: remove `min-h-full`; use `min-h-0` and flex growth through the tab
  shell and body.

## Validation

- [x] `mise run format`
- [x] Python suite: `3086 passed, 8 skipped`
- [x] Chromium `panel.spec.ts` and `timetable.spec.ts`, including the exact CI
  panel-height assertion and the legacy time-slot create route
- [x] `mise run check`
- [x] `tingle check --base origin/main` — 274 debt points paid off
- [x] `git diff --check`
- [x] Critical diff and stale-reference review

## Deliberate skips

- CodeRabbit suggested state-dependent sidebar rotation. Superseded by the
  fixed icon orientation requirement.
- CodeRabbit suggested omitting `context_data` from `assert_response`.
  That helper interprets omission as expecting `None`; `ANY` removes the
  tautology while following the project test convention for view context.
- Timetable layout selectors remain in E2E tests where coordinates and
  dimensions are the behavior under test.
