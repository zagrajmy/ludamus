# Plan: Flatten venues to a single self-referential Space tree

## Why

The current `Event → Venue → Area → Space` hierarchy (added in migrations
0033–0037) makes the site slow: every read from a `Session` to its `Event`
walks `agenda_item.space.area.venue.event` — four joins — and the same chain
appears in enrollment, safety, conflict-detection, and stats queries.

Two changes:

1. Collapse `Venue` + `Area` + `Space` into a single self-referential `Space`
   model (a node tree, max depth 7). Only **leaf** spaces (no children) can
   carry an `AgendaItem`. The panel section keeps the name **"Venues"**.
2. Give `Session` a direct `event` FK so no read ever has to walk the tree to
   find the event.

## Decision: `event` FK goes on `Session`, not `AgendaItem`

Two different paths reach `Event` today, and the flatten breaks both:

- **Unscheduled proposals** scope via the nullable `category` FK —
  `Session.objects.filter(category__event_id=…)` in `SessionRepository`.
- **Scheduled / enrollment / conflict / stats** walk
  `agenda_item.space.area.venue.event` — in the `Session.effective_participants_limit`
  and `Session.is_enrollment_available` properties, `SessionManager.has_conflicts`,
  `enrollment.py`, `safety.py`, and `SessionRepository` / `SpaceRepository`
  stat queries.

Once `Space` is a variable-depth tree, `space__area__venue__event` **cannot be
expressed as an ORM join** — you would walk N parents. A direct event
reference is therefore mandatory.

Put it on `Session` because:

- `Session` is what the panel lists and filters by event; it is also the object
  every hot property needs `event` from. Every deep-chain property collapses to
  `self.event`.
- It replaces the nullable `category__event` indirection with a direct, non-null
  owner — a proposal *belongs to* an event.
- `AgendaItem` reaches the event via `session__event` (a single constant join;
  `AgendaItem ⇄ Session` is one-to-one), so it needs no event column of its own.

Do **not** add `event` to `AgendaItem`. Revisit only if profiling proves the
`session__event` join is hot — every conflict/enrollment query already joins
`session`, so it will not be.

## Target model

```python
class Space(models.Model):
    event   = FK(Event, related_name="spaces")               # on EVERY node
    parent  = FK("self", null=True, related_name="children")  # null = root ("venue")
    name, slug
    capacity     = PositiveInt(null=True)   # meaningful on leaves
    description  = Text(blank=True)          # absorbs Venue.address + Area.description
    order, creation_time, modification_time
```

`event` is denormalized onto every node (not just roots) so
`Space.objects.filter(event=…)` fetches a whole tree in one query and leaf→event
is direct. Invariant: `child.event == parent.event`.

Invariants enforced in `clean()` / the Space service, **not** in the database —
one self-check test each, no recursive CHECK constraints or triggers:

- depth ≤ 7 (reject creating/moving a node whose chain would exceed 7);
- a space with children cannot receive an `AgendaItem`, and a space with an
  `AgendaItem` cannot receive children (leaf-only rule).

Slug uniqueness: unique per `(event, parent, slug)` among siblings. Roots
(`parent IS NULL`) are validated in `clean()` since SQL treats NULLs as
distinct.

---

## Deployment 1 — `Session.event` (independent perf/decoupling win)

Ships on its own; no UX change, fully reversible. Removes the deep chain from
`Session` and the nullable-category indirection.

### Step 1 — add and backfill `Session.event`, switch read paths

- Migration A (additive): add nullable `event = FK(Event, related_name="event_sessions")`.
- Migration B (data): backfill
  `event = coalesce(category.event, agenda_item.space.area.venue.event)`.
  Guard: a session with null `category` **and** no `agenda_item` has no event
  signal — the migration counts and reports these (expected: none). Decide
  per-case before finalizing rather than guessing a default.
- Migration C (finalize): make `event` non-null.
- Rewrite **only the deep-chain** `space__area__venue__event` references that the
  flatten will break. `category__event` keeps working (the flatten doesn't touch
  `category`), so those repo filters are deliberately left as-is; decoupling them
  from the nullable `category` is a later, optional cleanup, not required here:
  - `Session.effective_participants_limit` and `Session.is_enrollment_available`
    → `self.event` instead of `self.agenda_item.space.area.venue.event`.
  - `SessionManager.has_conflicts` → filter on `event_id`.
  - `can_enroll_users` / `get_used_slots` (`models.py`) → `session__event_id`.
  - Event-page session queryset gains `select_related("event")` +
    `prefetch_related("event__enrollment_configs")` so the new FK access stays
    N+1-free.
- Every Session-creation path sets `event_id`: `SessionData` gains `event_id`;
  the import engine, wizard (`mills/legacy.py`), and panel proposal-create
  populate it. Test factory `SessionFactory.event` defaults to `category.event`
  (a `LazyAttribute`) so the `session.event == category.event` invariant holds.
- Orphan note: production had **zero** sessions with null `category` and no
  `agenda_item`; the local dev DB had 559 junk rows (deleted locally, not via
  migration — the backfill stays prod-faithful).
- Verify: `mise run check && mise run test`. **Done — 2343 passed, lint clean.**

### Step 1b — drop `Session.sphere` (event subsumes it)

`Session.event` makes `Session.sphere` redundant (`event.sphere` derives it),
so the FK is removed. Migration `0098`: drop `sphere`, swap the unique constraint
`(slug, sphere)` → `(slug, event)`. Session slug uniqueness thus moves from
per-sphere to **per-event** — a relaxation (per-sphere was stricter), so no
existing rows conflict. `slug_exists`/`find_id_by_slug` take `event_id`;
`SessionData` drops `sphere_id`; the import engine drops `sphere_id` threading
(kept only where it still feeds `fetch_responses`); `SessionAdmin` `sphere` →
`event`.

Principle enforced (per review): **sessions are fetched in event scope or user
scope, never sphere scope.** Consequence — the enroll/accept/anonymous URLs,
which were `session/<id>/...` (sphere-guarded only because that was the sole
available scope), move under `event/<event_slug>/session/<id>/...` and fetch
`Session.objects.get(event__slug=event_slug, ..., id=session_id)`. Waitlist
notifications already carry `event_slug` on their DTOs, so their links use it
directly — no DTO change.

- Verify: `mise run check && mise run test`. **Done — 2343 passed, lint clean.**
- Playwright e2e (`promotion.auth.spec.ts` + `bootstrap_*.py` seeds) updated to
  the event-scoped `event/<event_slug>/session/<id>/enrollment/` path.

---

## Deployment 2 — Space gains a direct `event`; queries leave the deep chain

Additive schema plus a code switch to the new paths. Mirrors Deployment 1: just
denormalize `event` onto `Space` and move reads off the deep chain. `Venue` /
`Area` still exist and the panel still drives them. Reversible.

The tree shape (`parent`, `description`, root/mid nodes, `area` nullable) is
**deliberately deferred to Step 4**, where the panel rewrite is its only
consumer. Building it here would force `Space.area` nullable, breaking every
`space.area.venue.name` display walk with throwaway None-guards in code Step 4
rewrites anyway. Nothing in Deployment 2 reads `parent`/`description`.

### Step 2 — add and backfill `Space.event`

- Migration A (additive): add nullable `event = FK(Event, related_name="spaces")`.
- Migration B (data): backfill `event = area.venue.event` for every (leaf) space.
  `AgendaItem.space` FKs are untouched.
- Migration C (finalize): make `Space.event` non-null.
- Every Space-creation path sets `event_id` (repo `create`, the two venue-copy
  paths). `SpaceFactory.event` defaults to `area.venue.event`; raw
  `Space.objects.create(...)` in tests pass `event=` explicitly.
- Not user-visible. Verify in a shell.

### Step 3 — move every query off `space__area__venue__event`

- Replace the chain in `enrollment.py`, `safety.py`, the `SessionRepository` /
  `SpaceRepository` stat queries and subqueries with `session__event` or
  `space.event`.
- Replace the venue/area existence checks (`AgendaItem.objects.filter(space__area__venue_id=…)`
  etc.) with event- or space-scoped equivalents.
- Tests: enrollment, safety, conflict, stats integration tests pass on the new
  paths.
- Verify: `mise run check && mise run test`.

---

## Deployment 3 — unified panel, then drop the old models

The destructive deployment: new UI first in the same release, then the table
drops. Ships last.

### Step 4 — build the tree, then rewrite "Venues" as one recursive Space CRUD

- Schema: make `Space.area` nullable, add `parent` self-FK and `description`
  (deferred from Step 2 — see Deployment 2 note).
- Data migration (the tree-build deferred from Step 2): each `Venue` → a root
  `Space` (`parent=None`, `description=venue.address`, carry `order`); each
  `Area` → a mid `Space` (`parent=` its venue's new root,
  `description=area.description`); each existing leaf `Space` → `parent=` its
  area's new mid. `AgendaItem.space` FKs untouched — leaves keep their identity.
- Collapse the three view sets (`Venue*`, `Area*`, `Space*` in
  `panel/views/venues.py`) and three repositories into one `Space` tree CRUD:
  create (optional `parent`), edit, delete, reorder, with the leaf-only and
  depth-7 guards from the Space service. The `space.area.venue.name` display
  walks get rewritten to the tree here.
- One set of templates renders the tree; section keeps the name "Venues".
- DTOs: one `SpaceNode`/tree DTO replaces the Venue/Area/Space DTOs in
  `pacts/venues.py`.
- Tests: integration tests for create-under-parent, leaf-only rejection,
  depth-7 rejection, reorder, delete.
- Verify: `mise run check && mise run test`.

### Step 5 — drop `Venue`, `Area`, and `Space.area`

- Delete the `Venue` and `Area` models, the `Space.area` FK, and the now-dead
  repos / views / forms / templates / DTOs (`mills/venues.py`,
  `pacts/venues.py`, Venue/Area entries in `forms.py`, `admin.py`, `uow.py`,
  `inits/*`).
- Drop-tables migration (reversible only by restoring from Deployment 2).
- Update i18n (`locale/pl/LC_MESSAGES/django.po`) and the architecture docs.
- Verify: `mise run check && mise run test`; screenshots of the Venues panel in
  the PR.

---

## Open questions

1. Depth-7 limit — hard reject on the 8th level, or only stop the panel UI from
   nesting deeper? (Plan assumes hard reject in `clean()`.)
2. `capacity` / `description` on every node or only on leaves? (Plan keeps both
   nullable on every node; only leaves use `capacity`.)
3. Backfill orphans in Step 1: any sessions with null `category` and no
   `agenda_item`? Confirm the count is zero before finalizing the non-null
   migration.
