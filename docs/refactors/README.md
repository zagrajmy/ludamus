# Refactors in flight

A snapshot of the refactors currently underway, so any session can pick up
where the last one left off. One file per refactor holds the detail and the
**next step**; this README is the index and overall status.

_Describe state by class / function / module names, not line numbers or
counts — those churn every commit. Update the per-refactor files as work
lands; keep the table below in sync._

## Status at a glance

| # | Refactor | Status | Next step (short) |
| - | -------- | ------ | ----------------- |
| 1 | [GLIMPSE strangler: `adapters/` → layers](glimpse-strangler.md) | 🟡 in progress | Migrate Auth/Profile views out of `adapters/web/django/views.py` |
| 2 | [UoW → Services (`request.di.uow` → `request.services`)](services-di.md) | 🟡 early | Finish `timetable` (promote `TimetableService` to `request.services`), then `time_slots.py` |
| 3 | [Legacy module split (`*/legacy.py` → per-subdomain)](pacts-mills-split.md) | 🟡 in progress | Carve `notice_board` DTOs/services out of `legacy.py` |
| 4 | [`links/db/django` layout (split fat repositories)](links-db-layout.md) | 🔴 not started | Split `repositories.py` by aggregate group |
| 5 | [Panel object-scope authorization (IDOR)](panel-object-scope-authz.md) | 🟢 active branch | Audit `venues.py` and `proposals.py`, then `facilitators.py` |
| 6 | [HTMX adoption (frontend)](htmx-adoption.md) | 🟡 in progress | Convert one more multi-step/list page to HTMX partials |

Legend: 🟢 healthy/active · 🟡 partially done, steady-state · 🔴 not started.

## How these relate

Refactors 1–4 are the **GLIMPSE architecture migration** seen from four
angles, and they unblock each other:

```text
1 strangler      moves code out of adapters/ into the layered tree
2 services-di    replaces the UoW bag with per-service repo injection
3 module-split   breaks the legacy.py facades into per-subdomain modules
4 links-db       splits the fat repository/model files once they land in links
```

A view file typically gets touched by 1, 2 and 3 together: it moves into
`gates/`, swaps `request.di.uow` for `request.services`, and the DTOs/services
it needs get carved out of `legacy.py` along the way. Migrate **one view file
at a time** end to end rather than doing one angle globally.

Refactor 5 (authz) is a security hardening pass that rides on top of the panel
views as they are touched. Refactor 6 (HTMX) is independent of the backend
layering work.

## Reference material

- [target-architecture.md](target-architecture.md) — the target shape and
  rationale for refactors 1–4 (the GLIMPSE → hexagonal direction).
- [docs/agents/architecture.md](../agents/architecture.md) — current layer map,
  import rules, subdomain/bounded-context catalogue.
- [docs/agents/services-migration.md](../agents/services-migration.md) — the
  per-file recipe for refactor 2.
- [TODO.md](../../TODO.md) — the kanban; GLIMPSE-tagged items map to 1–4.
