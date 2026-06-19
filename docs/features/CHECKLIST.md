# Refinement checklist

Items `/tbd-refine` walks against each landed bullet. Trim or grow as the
project teaches you what you keep forgetting.

## Default items

- **Implementation-agnostic language** — scan stories for UI elements,
  interface verbs, internal tech names, model or field names, and
  literal button text. Would each story still hold on iOS or a CLI?
- **Story-only structure** — no context paragraphs, no motivation
  prose, no buried rules. H2 groups related stories by topic, never
  labels a single story.
- **Translations** — user-facing strings wrapped, i18n files updated.
- **Migrations** — schema changes have a migration; reversible if possible.
- **Error handling** — failure paths return useful errors; no silent swallows.
- **Accessibility** — keyboard reachable, semantic HTML, alt text on images.
- **Telemetry** — meaningful events logged for the new path.
- **Security** — authz checked; no new secrets in code.
- **Tests** — happy path covered; one edge case at minimum.

## Project-specific items

- **"test" reserved for pytest** — no production symbol, column, or
  field uses `test` / `tested`; use `check` / `validation` /
  `verification` instead.
- **Object-scope authorization (no cross-event / cross-sphere tampering)** —
  panel access only proves you manage the *current* sphere/event; it says
  nothing about the objects you name in the request. For every view that acts
  on an object identified by request-supplied data (URL `pk`/`slug`, or
  pks/ids in the POST/GET body), confirm the object belongs to the resolved
  `current_event`/sphere before reading or writing it. Check both:
  - the primary object — read it scoped (`read_by_slug(event_pk, …)` /
    `read_by_event(event_pk, pk)`) or read-then-compare
    (`read_event(pk).pk == current_event.pk`);
  - every related id taken from the body (space / manager / facilitator /
    field / time-slot / category pks, `presenter_id`, log pks) — intersect it
    against an event- or sphere-scoped set before persisting.
  Bare-pk repo methods (`read(pk)`, `update(pk)`, `m2m.set(...)`) trust the
  caller, so the scoping must happen at the view. Add a regression test that a
  foreign id returns 404/422 and changes nothing.
