# Plan 019: Show all schedule days side-by-side

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on.
> If a STOP condition occurs, stop and report instead of improvising.
>
> **Drift check (run first)**:
>
> ```sh
> git diff --stat 060b7a8e..HEAD -- \
>   src/ludamus/mills/chronology.py \
>   src/ludamus/pacts/chronology.py \
>   src/ludamus/gates/web/django/chronology/panel/views/timetable.py \
>   src/ludamus/templates/panel/timetable.html \
>   src/ludamus/templates/panel/parts/timetable-grid.html \
>   src/ludamus/client/src/timetable.ts
> ```
>
> If any file changed, compare this plan's current-state claims with live
> code before implementation. Material mismatch is a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (drag/drop coordinates and URL state span several layers)
- **Depends on**: —
- **Category**: feature
- **Planned at**: commit `060b7a8e`, 2026-07-23

## Outcome

The Schedule's Day filter offers **All** when an event has multiple
schedule dates. Selecting it renders one day board per date, ordered
chronologically and laid out side-by-side in one horizontally scrollable
row. This primarily serves blocks with one room across multiple days.

Default behavior stays unchanged: opening Schedule without `date`
selects the first available date. A one-day event shows one board and no
needless Day selector.

## Product decisions

- `date=all` is the canonical URL state. It survives HTMX refreshes,
  search, category/duration filters, pagination, and back links.
- All is opt-in, not the default.
- Day boards never collapse into a vertical stack on narrow screens.
  The containing row scrolls horizontally.
- Every board has a visible localized date heading and its own time axis.
  Dates may have different start/end windows.
- Room pagination applies once to the shared room set. The same room
  page appears in every day board.
- In All mode, the unscheduled-session pane is not availability-filtered
  to one date. Dragging onto a board still assigns that board's date/time.

## Current state

- `TimetableService.build_grid()` in
  `src/ludamus/mills/chronology.py` loads spaces, slot windows, and
  agenda items, then builds exactly one date's columns and time axis.
  Missing or invalid dates resolve to the first available date.
- `TimetableGridDTO` in `src/ludamus/pacts/chronology.py` mixes shared
  board data (spaces, groups, pagination) with one day's data (columns,
  labels, start, duration).
- `_parse_date_param()` in
  `src/ludamus/gates/web/django/chronology/panel/views/timetable.py`
  maps `date=all` to `None`, which currently means “first date”.
- `src/ludamus/templates/panel/timetable.html` serializes
  `grid.selected_date` into related URLs and shows the Day selector even
  when only one choice exists.
- `src/ludamus/templates/panel/parts/timetable-grid.html` renders one
  `#timetable-calendar`.
- `src/ludamus/client/src/timetable.ts` resolves one global calendar.
  Drop time, hover guide, and preferred-time overlays all read its
  start/duration. Rendering multiple boards without refactoring this
  would assign wrong times outside the first day.
- `UnscheduledSessionFilter.available_on` already accepts `None`.
  Repositories omit the availability predicate in that case, matching
  the required All-mode session list.

## Scope

### In scope

- DTO and service representation for one shared board with one or more
  day grids.
- `date=all` parsing, normalization, and propagation.
- Side-by-side day-board rendering.
- Drag/drop and preferred-time overlays scoped to the target day.
- Unit, integration, and Playwright regression coverage.
- Polish translation catalog update for new user-facing text.
- Wide and compact screenshots of All mode.

### Out of scope

- Changing the default from the first day to All.
- Showing different room pages or track filters per day.
- Vertical stacking on compact layouts.
- Broad migration of timetable views away from their existing
  `request.di.uow` use.
- Redesigning session cards, room pagination, or availability rules.

## Implementation

### Step 1: Model shared board data and per-day grids

In `src/ludamus/pacts/chronology.py`, add a DTO such as:

```python
class TimetableDayGridDTO(BaseModel):
    date: date
    columns: list[SpaceColumnDTO]
    time_labels: list[str]
    total_minutes: int
    event_start_iso: str
```

Reshape `TimetableGridDTO` to hold:

- shared `spaces`, `groups`, slot/snap values, pagination totals, and
  `available_dates`;
- `days: list[TimetableDayGridDTO]`;
- `selected_date: date | None`;
- `show_all_days: bool`.

Move `columns`, `time_labels`, `total_minutes`, and `event_start_iso`
off the top-level DTO. Do not keep duplicate compatibility fields.
Update all constructors and tests in the same change.

In `TimetableService.build_grid()`:

1. Add keyword argument `show_all_days: bool = False`.
2. Load spaces, slot windows, and agenda items once.
3. Resolve dates:
   - All mode: every available date, sorted;
   - single mode: valid selected date, otherwise first available date.
4. Extract a pure private helper that builds one `TimetableDayGridDTO`
   from a date, shared spaces, shared agenda items, and that date's
   windows.
5. Keep a column for every paginated space in every day grid, including
   rooms with no sessions that day.
6. Return `selected_date=None` only in All mode; empty schedules still
   return `days=[]`.

Do not implement All by calling `build_grid()` once per date. That
would repeat repository reads and room pagination.

**Verify**:

```sh
mise run test:unit
```

Expected: all unit tests pass. Add a focused service test with one room,
two dates, and one agenda item on each date. Assert:

- day grids are chronological;
- each grid contains only its own session;
- the room is present on both days;
- the agenda-item repository is read once.

### Step 2: Parse and preserve `date=all`

In
`src/ludamus/gates/web/django/chronology/panel/views/timetable.py`,
represent date selection explicitly rather than overloading `None`.
A small private parser/value object is acceptable; keep the shape local
to this module.

Required behavior:

- raw `all` → `show_all_days=True`, `selected_date=None`;
- valid ISO date → single-day mode;
- missing/invalid date → existing first-date fallback;
- after grid construction, expose normalized `date_param`:
  - `all` in All mode;
  - resolved `YYYY-MM-DD` in single-day mode.

Pass both values consistently through:

- full timetable page;
- timetable-grid HTMX partial;
- unscheduled-session list;
- browse-session pane and its filter/pagination requests;
- assign/unassign return URLs.

Use `available_on=None` for the session filter in All mode, while keeping
`date_param="all"` for URL generation.

Do not broaden the existing architecture migration while touching these
views.

**Verify**:

```sh
mise run test:int
```

Expected: all integration tests pass. Add cases proving:

- `?date=all` renders all date headings on the full page;
- the grid partial does the same;
- search/filter/pagination links retain `date=all`;
- an invalid date still resolves to the first date;
- a single-date event omits the Day selector.

### Step 3: Render day boards side-by-side

In `src/ludamus/templates/panel/timetable.html`:

- render the Day selector only when `available_dates|length > 1`;
- add translated option `All` with value `all`;
- mark it selected from `grid.show_all_days`;
- use `date_param`, never `selected_date|date`, in generated URLs.

In `src/ludamus/templates/panel/parts/timetable-grid.html`:

- keep track controls and room pagination shared;
- render `grid.days` inside one `flex`/`width-max` row and one outer
  horizontal-scroll container;
- render one `.timetable-calendar` section per day;
- add a localized, visible date heading per section;
- put each day's start/duration data on its own calendar element;
- keep fixed room-column widths so day boards remain side-by-side;
- avoid nested horizontal scrollers;
- retain existing empty/no-room/no-slot states.

Prefer the existing tessera components and Tailwind conventions.
Do not add a CSS abstraction unless the layout cannot be expressed
clearly with the existing timetable classes plus `extra_class`.

Update `src/ludamus/locale/pl/LC_MESSAGES/django.po` using the normal
message workflow. Translate All consistently with surrounding filter
copy.

**Verify**:

```sh
mise run lint:djlint
mise run messages-check
mise run build-frontend
```

Expected: templates format cleanly, translations are fresh, frontend
build succeeds.

### Step 4: Scope interactions to the target calendar

Refactor `src/ludamus/client/src/timetable.ts` from one global calendar
to multiple calendar roots:

- query `.timetable-calendar` as a collection;
- add `calendarForColumn(column)` using `closest`;
- calculate pointer time from the target column's calendar start;
- place hover/drop guides relative to that calendar;
- render preferred-time overlays separately for each calendar using
  that calendar's date window and columns;
- keep selection/active-column state global so a selected session can
  be assigned on any day;
- keep HTMX history behavior based on `location.search`, preserving
  `date=all`.

Avoid duplicate element IDs inside the repeated boards. Shared global
guides may keep unique IDs if they are moved between calendar roots.

**Verify**:

```sh
mise run ts-check
mise run lint-client
mise run build-frontend
```

Expected: all commands exit 0.

### Step 5: Add browser regression coverage

Extend `tests/e2e/scripts/bootstrap_timetable.py` with a second date
while preserving the existing first date and its default behavior.
Use unique session names so existing selectors stay unambiguous.

In `tests/e2e/tests/timetable.spec.ts`, add a serial All-mode test:

1. Open Schedule with `date=all`.
2. Assert two `.timetable-calendar` boards and two distinct headings.
3. Assert the second board's bounding-box `x` is greater than the
   first board's right edge (side-by-side, not stacked).
4. Select a unique unscheduled session and assign it into the second
   day's room.
5. Assert the assignment's date/time reflects the second board, not the
   first board.
6. Undo the assignment so the serial fixture remains reusable.
7. Repeat the layout assertion at a compact viewport and confirm the
   outer row scrolls horizontally.

Use accessible selectors for controls and stable data attributes for
calendar identity. Do not key the test to pixel colors.

**Verify focused test**:

```sh
mise run test:e2e -- tests/timetable.spec.ts \
  --project=chromium --grep "all days"
```

Expected: focused test passes.

### Step 6: Full verification and visual review

Run:

```sh
mise run test:py
mise run test:e2e
mise run check
mise run lint:tingle
```

Expected: all commands exit 0 and debt does not grow on net.

With the local server running, capture authenticated screenshots for:

- multi-day All mode at a wide viewport;
- the same page at a compact viewport showing horizontal overflow;
- single-day mode showing no Day selector.

Use the repository screenshot workflow where authentication permits it;
otherwise capture from the authenticated Playwright fixture. Include the
affected-page screenshots in the PR description.

Critically review:

- a session dropped on day two receives day two's timestamp;
- preferred-time overlays align independently on every date;
- browser Back/Forward and HTMX refresh keep `date=all`;
- one-day and zero-slot states remain clean;
- keyboard focus and labels distinguish each day;
- no nested horizontal scroll trap appears.

## Expected files

- `src/ludamus/pacts/chronology.py`
- `src/ludamus/mills/chronology.py`
- `src/ludamus/gates/web/django/chronology/panel/views/timetable.py`
- `src/ludamus/templates/panel/timetable.html`
- `src/ludamus/templates/panel/parts/timetable-grid.html`
- `src/ludamus/client/src/timetable.ts`
- `src/ludamus/locale/pl/LC_MESSAGES/django.po`
- `tests/unit/test_chronology_mills.py`
- relevant timetable integration tests under
  `tests/integration/web/panel/`
- `tests/e2e/scripts/bootstrap_timetable.py`
- `tests/e2e/tests/timetable.spec.ts`

## Done criteria

- [ ] Multi-date schedules expose `Day: All`; single-date schedules do
  not show a one-choice selector.
- [ ] `date=all` renders every day exactly once, chronological and
  side-by-side.
- [ ] Shared room pagination and track filtering affect every day.
- [ ] Session/filter/HTMX/back URLs preserve `date=all`.
- [ ] Dropping on any board uses that board's date and time.
- [ ] Preferred-time overlays are correct per board.
- [ ] Service repository reads are not multiplied by day count.
- [ ] Unit, integration, focused E2E, full E2E, and `mise run check`
  pass.
- [ ] Wide and compact screenshots are reviewed and attached to the PR.

## STOP conditions

- Live code materially diverges from the current-state description.
- A shared room page cannot be reused across dates without changing
  current track/space semantics.
- Assigning a session requires a single selected date elsewhere in the
  backend contract, making `selected_date=None` ambiguous beyond this
  view.
- Correct compact behavior would require nested horizontal scrolling.
