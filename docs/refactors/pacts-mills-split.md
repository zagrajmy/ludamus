# 3. Legacy module split (`*/legacy.py` → per-noun)

**Status:** 🟡 in progress
**Tracked in TODO:** "Split mills/pacts/inits into packages per GLIMPSE layer
rules" (GLIMPSE)

## Goal

Break the catch-all `legacy.py` modules in `pacts/` and `mills/` into
per-noun files (`event`, `user`, `sphere`, `encounter`, `party`),
mirrored across the two layers, and fill in `specs/` with the business
invariants those mills currently inline. Retire the wildcard facades.
New carves use noun names; modules already carved under legacy subdomain
names (`chronology`, `multiverse`, `submissions`, `crowd`) keep them until
an opportunistic rename — the `old-subdomain-loc` tingle metric tracks
that debt.

## Why

`pacts/__init__.py` and `mills/__init__.py` are `from ...legacy import *`
facades — the pre-existing legacy exception in CLAUDE.md. They keep the whole
domain in one undifferentiated namespace, which works against the noun map
and against the ~12-members-per-level rule. The target is
`pacts/{noun}.py ↔ mills/{noun}.py`, cut into `{noun}/{verb}.py` only when
a noun grows fat.

## Current state

**Still in the catch-all `legacy.py` modules:**

- `pacts/legacy.py` — the bulk of the DTOs, write `TypedDict`s, enums and
  errors for every noun (`EncounterDTO`, `SessionDTO`, `EventDTO`,
  `UserDTO`, `SpaceDTO`, `TrackDTO`, `NotFoundError`, …).
- `mills/legacy.py` — `EncounterService`, `ProposeSessionService`,
  `PanelService`, `AcceptProposalService`, `AnonymousEnrollmentService`,
  `check_proposal_rate_limit`, and the calendar/ICS/share-code helpers.

**Already carved (still under legacy subdomain names):**

- `pacts/chronology.py` — timetable + CFP DTOs and the
  `CFPPersonalDataFieldServiceProtocol` (`TimetableGridDTO`, `ConflictDTO`,
  `SessionPlacement`, `HeatmapDTO`, `PersonalDataFieldFormContextDTO`, …).
- `pacts/multiverse.py` — sphere panel + connections contracts.
- `pacts/services.py` — `ServicesProtocol`, `TransactionProtocol`.
- `mills/chronology.py` — `TimetableService`, `ConflictDetectionService`,
  `TimetableOverviewService`, `CFPPersonalDataFieldService`.
- `mills/multiverse.py` — `ConnectionsService`, `SpherePanelService`.
- `specs/encounter.py`, `specs/proposal.py` — seeded but nearly empty.

`pacts/__init__.py` → `from ludamus.pacts.legacy import *`
`mills/__init__.py` → `from ludamus.mills.legacy import *`

So new code can already `from ludamus.pacts import NotFoundError` while the
symbol still physically lives in `legacy.py`.

## Done so far

- `chronology` and `multiverse` files exist in both `pacts` and `mills` and
  hold the already-migrated services/DTOs.
- `specs/` directory exists with two tiny seed files.

## Next step

Carve the **encounter** noun out of `legacy.py`, since it is already fully
migrated in `gates`/`links` and is self-contained:

1. Create `pacts/encounter.py`; move `EncounterDTO`, `EncounterRSVPDTO`,
   `EncounterData`, `EncounterDetailResult`, `EncounterIndexItem`,
   `EncounterIndexResult` and related types out of `pacts/legacy.py`.
2. Create `mills/encounter.py`; move `EncounterService` and the calendar /
   ICS / share-code helpers (`generate_ics_content`, `google_calendar_url`,
   `outlook_calendar_url`, `generate_share_code`, `render_markdown`).
3. Update imports at the use sites (`gates/web/django/notice_board/`,
   `inits/`). Prefer importing from the new module path directly rather than
   leaning on the `__init__` facade for the moved symbols.
4. Run `mise run check` (importlinter) + `mise run test:py`.

Encounter is the cleanest first cut because nothing else depends on its DTOs.
The **event** noun (legacy `chronology` + `submissions`) is the fat one:
carve it out of `legacy.py` by verb — `propose` (proposals, categories,
fields, requirements, facilitators), `enroll`, `schedule`, `present` — rather
than into one giant `pacts/event.py`. Contracts currently parked in
`pacts/chronology.py` / `mills/chronology.py` move into the verb cuts as they
are carved. Event goes last, after the smaller nouns are out.

## Definition of done

- `pacts/legacy.py` and `mills/legacy.py` are gone; `__init__.py` files are
  empty (no wildcard re-exports), per the CLAUDE.md default.
- Each noun has matching `pacts/` and `mills/` modules, cut by verb
  where the ~12-members rule demands it.
- `specs/` holds the invariants currently hard-coded inside mills (e.g. rate
  limits, session caps) and is imported only by `mills`.
