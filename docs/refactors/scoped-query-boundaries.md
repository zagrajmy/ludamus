# 7. Scoped query boundaries (baked-in invariant filters)

**Status:** 🔴 not started — deferred idea, no branch.

## Goal

For data-access surfaces that carry a hard invariant — "the public only ever
sees **scheduled** sessions", "a session read in the panel is always scoped to
the **current event**" — bake that invariant into a single scoped source so no
call site can accidentally query outside the boundary. The invariant lives in
one place, not re-typed (and forgotten) at every `.filter(...)`.

## Why

Today the invariant is a `.filter(agenda_item__isnull=False)` (or
`event_id=…`) repeated inline at each call site. It is correct only as long as
every author remembers to add it. The waitlist-count fix in
`forms.py::_can_join_waitlist` was exactly this class of bug: a new query that
should have been scheduled-only counted unscheduled sessions because the filter
was forgotten. `SessionRepository.list_sessions_by_event` is the next hazard —
it returns all sessions and is one careless reuse away from leaking unscheduled
sessions to a public view.

## The two shapes (pick per case)

- **Scoped model manager** — native Django, ~5 lines, no DTO work. Best when the
  consumers need live models (prefetch / annotate / `.exclude()` chains), which
  is the case for the legacy public views.

  ```python
  class ScheduledSessionManager(models.Manager):
      def get_queryset(self):
          return super().get_queryset().filter(agenda_item__isnull=False)

  class Session(...):
      objects = SessionManager()       # unchanged, sees everything
      scheduled = ScheduledSessionManager()
  ```

  Call sites swap `Session.objects.filter(...)` → `Session.scheduled.filter(...)`.

- **Scoped repository** — a dedicated repo (e.g. `PublicSessionRepository`)
  whose every method bakes in the filter and returns DTOs. Proper GLIMPSE shape,
  but only pays off once the consumers are DTO-based. Today the public consumers
  are legacy model views, so this needs the strangler migration (refactor 1)
  first or it forces a view rewrite alongside.

## Candidate boundaries

- **Public / enrollment sessions → scheduled only.** Consumers:
  `EventPageView.get_context_data` (agenda query) and
  `_get_session_or_redirect` + its `AgendaItem…exists()` gate (enroll flow).
  Both already filter inline today; the scoped source removes the "remember to
  filter" footgun.
- **Panel session reads → current-event scoped.** Overlaps with refactor 5
  (object-scope authz): a `read_by_event(event_pk, pk)` that can't return a
  foreign-event row is the same idea applied to authorization.

## Relation to other refactors

Sits between refactor 4 (split fat repositories) and refactor 5 (object-scope
authz). The manager form is independent and shippable now; the repository form
should follow the public views into `gates/` under refactor 1 rather than
rewrite them ahead of it.

## Next step

When picked up: start with the `Session.scheduled` manager and switch the two
public call sites — smallest diff, removes the footgun, no DTO migration. Defer
the full `PublicSessionRepository` until the public views are DTO-based.
