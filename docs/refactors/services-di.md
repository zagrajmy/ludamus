# 2. UoW → Services (`request.di.uow` → `request.services`)

**Status:** 🟡 early — a few services migrated, most views still on the UoW bag
**Recipe:** [docs/agents/services-migration.md](../agents/services-migration.md)
**Reference impl:** the `personal_data_fields` family

## Goal

Replace the legacy `request.di.uow.<repo>` surface — a single UoW object that
is both a transaction boundary and a repo bag — with
`request.services.<service_name>.<method>(...)`. Views stop reaching into
repos; services take only the specific repo protocols they touch plus a
`TransactionProtocol`.

## Why

UoW forces every consumer to see every repo and to own its own
`with uow.atomic()` blocks. Splitting it into a flat **Repository Registry**
(internal to `inits`), a flat **Services** namespace (`request.services`), and
a **TransactionProtocol** gives each service a two-line dependency list and ISP
at the boundary. Unit tests stop mocking a whole UoW.

## Current state

Strangler fig: `RepositoryInjectionMiddleware` (attaches `request.di.uow`) and
`ServiceInjectionMiddleware` (attaches `request.services`) run in parallel. A
view file uses one shape, never both. `request.di.uow` is still the dominant
surface; only a handful of views use `request.services`.

- **The UoW bag** — `UnitOfWork` (`links/db/django/uow.py`) still exposes every
  repository as a `@cached_property`. The parallel **Repository Registry**,
  `Repositories` (`inits/repositories.py`), so far exposes only
  `personal_data_fields`, `proposal_categories`, `connections`, `spheres`,
  `events`.
- **Services wired into `request.services`** — `Services` (`inits/services.py`)
  exposes `personal_data_fields` (`CFPPersonalDataFieldService`), `connections`
  (`ConnectionsService`), `sphere_panel` (`SpherePanelService`).
- **View files already on `request.services`** — `personal_data_fields.py`
  (chronology panel), `multiverse/access.py`, and
  `multiverse/panel/views/{base,connections}.py`.

### Halfway state to watch — `TimetableService`

`mills/chronology.py` now holds `TimetableService`, `ConflictDetectionService`
and `TimetableOverviewService` (logic pulled out of `timetable.py`), but the
view constructs them as `TimetableService(uow)` — they take the **whole UoW**
and are **not** wired into `request.services`. This is a partial migration:
domain logic left the gate, but the target shape (specific repo protocols +
`TransactionProtocol`, exposed on `request.services`) is not reached. Don't
mistake "logic is in mills" for "migrated".

### Panel view files still on `request.di.uow`

Roughly largest surface first: `venues.py`, `cfp.py`, `proposals.py`,
`session_fields.py`, `facilitators.py`, `event_settings.py`, `tracks.py`,
`timetable.py`, `time_slots.py`, `base.py`, `index.py`. Plus
`notice_board/views.py`, `context_processors.py`, `chronology/views.py`, and
everything still in `adapters/web/django/views.py` + `middlewares.py`.

## Next step

Two reasonable fronts — prefer finishing what's half-done before opening new
ground:

1. **Finish `timetable`.** The logic already lives in `TimetableService` /
   `ConflictDetectionService` / `TimetableOverviewService`. Promote them to the
   target shape: constructors take specific repo protocols (`sessions`,
   `agenda_items`, `spaces`, `schedule_change_logs`, …) + `TransactionProtocol`
   instead of `uow`; add the leaves to `inits/repositories.py`; expose
   `request.services.timetable`; drop `TimetableService(uow)` from
   `timetable.py`. This converts a halfway migration into a complete one — the
   smallest conceptual leap left.
2. **Then `time_slots.py`** — the smallest panel view still fully on
   `request.di.uow`, a clean greenfield application of the recipe: add a
   `TimeSlotsService` protocol + DTOs to `pacts/chronology.py`, implement it in
   `mills/chronology.py` (transaction + time-slot/event repos), wire it, and
   rewrite the view to `request.services.time_slots.*`. It carries the
   time-slot-overlap validation now in `PanelService.validate_time_slot`
   (legacy mills), so the migration also gives that logic a properly-scoped
   home.

For either, add unit tests mocking the specific repo protocols; existing
integration tests are the regression guard.

## Definition of done

- Every view file uses `request.services`; zero `request.di.uow` call sites.
- `RepositoryInjectionMiddleware` and `request.di.uow` are deleted.
- Decide whether non-repo links (`cache`, `ticket_api`, `gravatar_url`) move
  onto `request.services` or stay on a slimmed `request.di` (defer until a
  consumer migration forces the choice — don't pull them in preemptively).
