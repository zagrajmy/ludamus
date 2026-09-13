---
status: draft
updated: 2026-09-13
points: 10
depends: [02]
---

# Timetable shaped by the event

## Days and hours

As an organiser, I want the timetable to show every day of my event, so
that I can schedule from the first hour to the last without defining
anything else.

As an organiser, I want the grid to run from my event's start to its end,
with `DayTurnover` deciding where one day becomes the next, so that a
late-night game has a place on the grid.

As an organiser, I want to place a session at any time within the event, so
that proposer availability never blocks a placement I decide on.

As an organiser, I want a placement outside the event's dates refused, so
that nothing lands on a day that does not exist.

As an organiser, I want a placement that ignores a proposer's stated
availability reported afterwards, so that I can decide whether to keep it.

As an organiser, I want availability windows to overlap freely, so that a
two-hour and a four-hour rhythm can coexist for different kinds of
sessions.

## Overview

As a coordinator, I want scheduled hours, room count and the occupancy map,
so that I judge progress on numbers that mean something.

As a coordinator, I want no capacity figure, no hours-left and no filled
percentage, so that I am not reading a number computed against every empty
night hour of a multi-day event.

As a coordinator, I want the occupancy map to cover every event day and
room, so that I spot empty stretches at a glance.

As a coordinator, I want the overview to tell me to add rooms when there
are none, so that an empty page explains itself.

## What it touches

- `slot_windows_by_local_date` and `_shared_day_span` take windows derived
  from `Event.start_time`/`Event.end_time` and `DayTurnover`;
  `build_heatmap` too. Remove `_require_placement_in_time_slots` and
  `PlacementRejection.OUTSIDE_TIME_SLOTS`; keep event-date bounds.
- Only once the timetable stops reading slots: drop the overlap check in
  `TimeSlot.validate_unique`, `PanelTimeSlotsService`, and
  `TimeSlotValidationError.OVERLAPS_EXISTING_SLOT`.
- `CapacityHoursDTO` loses `capacity_hours`, `hours_to_fill` and
  `filled_pct`; `TimetableOverviewService.capacity_hours` stops computing
  them and is renamed for what is left. The overview template drops the
  progress bar and the two tiles. Keeping "hours to fill" while dropping the
  percentage would keep the distorted number and lose the legible one: both
  are `capacity_hours - scheduled_hours` over the same widened denominator.
- Empty-state copy no longer mentions time slots.
- Programme windows narrower than the event — a day schedule of lectures and
  a night schedule of horror films, per room — are issue #1293, not this
  feature.
