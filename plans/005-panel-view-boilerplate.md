# Plan 005: Extract the shared panel-view boilerplate into a base view

> **Executor instructions**: Follow this plan step by step. Run every
> verification command before moving on. On any STOP condition, stop and
> report. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 337cdde7..HEAD -- src/ludamus/gates/web/django/chronology/panel/views/`
> Mismatch with "Current state" = STOP. (Open PRs #361/#362 touch panel views —
> check they haven't landed conflicting changes.)

## Status

- **Priority**: P2
- **Effort**: M (1–2 days)
- **Risk**: LOW (pure refactor under existing integration tests)
- **Depends on**: none (but reduces cost of every upcoming panel feature in the
  Kapitularz umbrella issue #326 — announcements, confirm-items, discounts,
  organizer permissions all add panel views)
- **Category**: tech-debt
- **Planned at**: commit `337cdde7`, 2026-06-10

## Why this matters

Every panel page view repeats the same opening dance: call
`get_event_context(slug)`, bail to `panel:index` when the event is missing,
set `active_nav` / `active_tab` / `tab_urls`, render a template. The repo's own
authors marked it: several files start with
`# TODO(fancysnake): Extract common view boilerplate` and
`# pylint: disable=duplicate-code`. ~70 view classes across ~13 files inherit
`(PanelAccessMixin, EventContextMixin, View)` and copy this block. The
Kapitularz umbrella (#326) plans at least six more panel features, and the XL
"organizer permissions" task will have to touch the permission/context path in
every one of these views — collapsing the boilerplate first makes that a
one-place change instead of a 70-place retrofit.

## Current state

- `src/ludamus/gates/web/django/chronology/panel/views/base.py` — the shared
  mixins. `PanelAccessMixin.test_func` checks sphere-manager status;
  `EventContextMixin.get_event_context(slug)` returns
  `(context_dict, EventDTO | None)` and flashes "Event not found." on miss
  (lines 35–97).
- The repeated consumer pattern, e.g.
  `src/ludamus/gates/web/django/chronology/panel/views/cfp.py:31-55`:

  ```python
  class CFPPageView(PanelAccessMixin, EventContextMixin, View):
      request: PanelRequest

      def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
          context, current_event = self.get_event_context(slug)
          if current_event is None:
              return redirect("panel:index")

          context["active_nav"] = "cfp"
          context["active_tab"] = "types"
          context["tab_urls"] = cfp_tab_urls(slug)
          context["categories"] = self.request.di.uow.proposal_categories.list_by_event(
              current_event.pk
          )
          ...
          return TemplateResponse(self.request, "panel/cfp.html", context)
  ```

  Same shape in `tracks.py` (`TracksPageView.get`, lines ~48-60),
  `session_fields.py`, `time_slots.py`, `venues.py`, `proposals.py`,
  `facilitators.py`, and the multiverse panel under
  `src/ludamus/gates/web/django/multiverse/panel/views/`.

- Files carrying the TODO marker (grep `Extract common view boilerplate`):
  `session_fields.py`, `tracks.py`, `venues.py`, `time_slots.py` (at minimum).

- Tests: every panel view has integration tests under
  `tests/integration/web/` (e.g. `tests/integration/web/multiverse/test_sphere_settings.py`),
  using the `assert_response` utility. These are the regression net.

- Conventions: strict mypy (`disallow_any_expr` relaxed for gates), ruff ALL,
  no noqa/type-ignore additions, docstrings only when unavoidable, GLIMPSE
  layering — gates must not import links/inits (`import-linter` contract in
  `pyproject.toml`; runs via `mise run il`).

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Panel view tests | `poetry run pytest tests/integration/web -q -k "panel or cfp or track or venue or time_slot or session_field"` | all pass |
| Full suite | `mise run test` | all pass |
| Lint+types+imports | `mise run prcheck` | exit 0 |

## Scope

**In scope**:
- `src/ludamus/gates/web/django/chronology/panel/views/base.py` (add the base class)
- The GET handlers of page views in
  `src/ludamus/gates/web/django/chronology/panel/views/*.py` — migrate them
  to the base class **incrementally, one file per commit**

**Out of scope**:
- POST/action handlers' business logic (only their shared *prelude* may move)
- `src/ludamus/gates/web/django/multiverse/panel/views/` — second wave, only
  if the chronology migration lands cleanly and time remains
- Any `request.di.uow` → `request.services` migration (separate program); the
  base class must work with BOTH access styles
- `timetable.py` and `integrations.py` if their handlers deviate from the
  simple shape — skip rather than force-fit
- Templates

## Git workflow

- Branch: `advisor/005-panel-view-boilerplate`
- One commit for the base class, then one commit per migrated file (keeps
  review and bisect sane).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add `EventPanelPageView` to `base.py`

A template-method base for the common GET shape:

```python
class EventPanelPageView(PanelAccessMixin, EventContextMixin, View):
    request: PanelRequest

    template_name: ClassVar[str]
    active_nav: ClassVar[str | None] = None
    active_tab: ClassVar[str | None] = None

    def get(self, _request: PanelRequest, slug: str) -> HttpResponse:
        context, current_event = self.get_event_context(slug)
        if current_event is None:
            return redirect("panel:index")
        if self.active_nav is not None:
            context["active_nav"] = self.active_nav
        if self.active_tab is not None:
            context["active_tab"] = self.active_tab
        extra = self.get_page_context(current_event, slug)
        if isinstance(extra, HttpResponse):  # escape hatch for redirects
            return extra
        context.update(extra)
        return TemplateResponse(self.request, self.template_name, context)

    def get_page_context(
        self, event: EventDTO, slug: str
    ) -> dict[str, Any] | HttpResponse:
        return {}
```

Adapt typing details to what mypy accepts in this package (gates have
`disallow_any_explicit = false`, so `dict[str, Any]` is fine). Keep the mixin
MRO identical to today's `(PanelAccessMixin, EventContextMixin, View)`.

**Verify**: `mise run prcheck` → exit 0.

### Step 2: Migrate `cfp.py` page views

`CFPPageView` becomes:

```python
class CFPPageView(EventPanelPageView):
    template_name = "panel/cfp.html"
    active_nav = "cfp"
    active_tab = "types"

    def get_page_context(self, event: EventDTO, slug: str) -> dict[str, Any]:
        return {
            "tab_urls": cfp_tab_urls(slug),
            "categories": self.request.di.uow.proposal_categories.list_by_event(
                event.pk
            ),
            "category_stats": (
                self.request.di.uow.proposal_categories.get_category_stats(event.pk)
            ),
        }
```

Migrate every view in the file whose GET matches the pattern; leave divergent
ones (custom redirects, form handling in GET) untouched. Remove the
`# pylint: disable=duplicate-code` / TODO header **only when the file no
longer needs it** (i.e. the duplicated block is gone).

**Verify**: `poetry run pytest tests/integration/web -q -k cfp` → all pass;
`mise run prcheck` → exit 0. Commit.

### Step 3: Repeat per file

Same treatment for `tracks.py`, `session_fields.py`, `time_slots.py`,
`proposals.py`, `facilitators.py`, `venues.py` — one commit each, running that
file's tests after each. Skip any view whose GET does more than
context-build-and-render (note skips in the final report).

**Verify after each file**: its `pytest -k` slice passes.

### Step 4: Full gate

**Verify**: `mise run test` → all pass; `mise run prcheck` → exit 0 (pylint's
`duplicate-code` should now be quieter, never noisier).

## Test plan

No new tests required — this is a behavior-preserving refactor and every view
is already integration-tested (per `docs/TESTING_STRATEGY.md`, gates are
tested via integration tests). The full existing suite is the gate. If you
find a migrated view with NO test exercising its GET, write one minimal
`assert_response` test in the matching `tests/integration/web/...` module,
modeled on its neighbors, BEFORE migrating that view.

## Done criteria

- [ ] `EventPanelPageView` exists in `base.py` and at least 5 files' page views use it
- [ ] `grep -rn "Extract common view boilerplate" src/` matches only in files with views intentionally skipped (list them in the completion report)
- [ ] `mise run test` exits 0
- [ ] `mise run prcheck` exits 0 (including import-linter)
- [ ] Only in-scope files modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

- A view's GET subtly differs (extra permission check, conditional redirect,
  per-request tab logic) in a way the hooks can't express without widening the
  base class — skip it and report rather than adding base-class flags.
- Integration tests for a file fail after migration and the cause isn't an
  obvious mechanical mistake — revert that file's commit and report.
- Open PR #361 (import skeleton) or #362 (audit log) lands mid-work and
  touches the same files — rebase, re-run the drift check, and re-verify
  excerpts before continuing.

## Maintenance notes

- The upcoming "organizer permissions" (umbrella #326, XL) should hook into
  `EventPanelPageView` / `PanelAccessMixin` — that's the point of this refactor;
  reviewers should reject new panel page views that bypass the base class.
- When the strangler-fig migration reaches these files, only
  `get_page_context` bodies change (`request.di.uow.*` → `request.services.*`);
  the base class is agnostic.
- Deferred: the multiverse panel (`gates/web/django/multiverse/panel/views/`)
  second wave; POST-handler prelude dedup.
