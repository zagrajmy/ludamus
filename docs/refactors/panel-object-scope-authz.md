# 5. Panel object-scope authorization (cross-event / cross-sphere IDOR)

**Status:** 🟢 active — current branch `fix/panel-cross-event-idor`
**Tracked in:** `docs/features/CHECKLIST.md` (project-specific item)

## Goal

Close cross-event / cross-sphere IDOR holes in the panel. Panel access only
proves you manage the **current** sphere/event; it says nothing about the
objects named in the request. Every panel view that acts on an object
identified by request-supplied data (URL `pk`/`slug`, or pks/ids in the
POST/GET body) must confirm that object belongs to the resolved
`current_event`/sphere before reading or writing it.

## Why

Bare-pk repo methods (`read(pk)`, `update(pk)`, `m2m.set(...)`) trust the
caller. An organiser of event A can otherwise pass event B's space, manager,
field, time-slot or category pk in a form body and mutate it. The access mixin
does not catch this because the pk is data, not the route the mixin guards.

## The rule (from CHECKLIST.md)

For every such view, check **both**:

- **the primary object** — read it scoped (`read_by_slug(event_pk, …)` /
  `read_by_event(event_pk, pk)`) or read-then-compare
  (`read_event(pk).pk == current_event.pk`);
- **every related id from the body** — space / manager / facilitator / field /
  time-slot / category pks, `presenter_id`, log pks — intersect against an
  event- or sphere-scoped set before persisting.

Add a regression test that a foreign id returns 404/422 and changes nothing.

## Current state

Commits on the branch, each hardening one area + adding regression tests:

- `5ece8956` timetable assign / unassign / revert scoped to current event
- `43483d64` track space/manager pks scoped to event and sphere
- `4086dbcc` CFP requirement pks scoped to current event
- `631bf77e` moved the timetable cross-event guards out of module-level helpers
  in the gate and **into `TimetableService`** (assign/unassign/revert now take
  `event_pk` and reject sessions, spaces or logs outside the event with
  `NotFoundError`); views became thin parse → call → 422. Adds mills-level
  scope-rejection tests.
- plus session-field and personal-data-field create/edit tests

This makes `TimetableService` *self-guarding* — the scope check lives with the
write, matching `CFPPersonalDataFieldService`, rather than in the view. That is
the preferred end shape for this refactor: scoping enforced in the service, not
re-derived per view.

## Audited so far

`timetable` (now guarded inside `TimetableService`), `tracks`, `cfp`
(requirement pks), `session_fields`, `personal_data_fields`.

## Next step

Audit the remaining body-id-accepting panel views, largest attack surface
first:

1. **`venues.py`** — venue/area/space create/edit/reorder/delete; confirm each
   venue/area/space pk resolves under `current_event`, and reorder id lists are
   intersected against the event's spaces.
2. **`proposals.py`** — accept/assign flows take `presenter_id`, category and
   session pks from the body; scope each to the event.
3. Then `facilitators.py` (facilitator/user pks) and `event_settings.py`.

For each: scope the primary read, intersect body ids against an event/sphere
set, add a regression test that a foreign id returns 404/422 and mutates
nothing.

## Definition of done

- Every panel view that consumes a request-supplied id is audited and scoped.
- Each has a regression test proving a foreign id is rejected without side
  effects.
- The CHECKLIST item can be walked clean by `/tbd-refine` against new panel
  stories.
