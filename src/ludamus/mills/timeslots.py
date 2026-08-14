"""Shared local-day window helpers for chronology mills and schedule gates.

Time slots are proposer availability windows ("when could you run your
session?"), not schedule display units — rendered timetables show the real
session start and end times instead. Both still need the same local-midnight
split, so the pure interval math lives here.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ludamus.pacts import TimeSlotDTO

type SlotWindow = tuple[datetime, datetime]


def interval_windows(*, start: datetime, end: datetime, tz: tzinfo) -> list[SlotWindow]:
    # An interval spanning multiple local dates contributes one (start, end)
    # window to each date it touches, clamped to that date's [00:00, 24:00)
    # range. One definition of "a day", shared by slots and by scheduled items.
    local_start = start.astimezone(tz)
    local_end = end.astimezone(tz)
    windows: list[SlotWindow] = []
    days_span = (local_end.date() - local_start.date()).days + 1
    for offset in range(days_span):
        cursor_date = local_start.date() + timedelta(days=offset)
        day_start = datetime.combine(cursor_date, datetime.min.time(), tzinfo=tz)
        day_end = day_start + timedelta(days=1)
        window_start = max(local_start, day_start)
        window_end = min(local_end, day_end)
        if window_start < window_end:
            windows.append((window_start, window_end))
    return windows


def slot_windows(slot: TimeSlotDTO, tz: tzinfo) -> list[SlotWindow]:
    return interval_windows(start=slot.start_time, end=slot.end_time, tz=tz)


def slot_windows_by_local_date(
    slots: list[TimeSlotDTO], tz: tzinfo
) -> dict[date, list[SlotWindow]]:
    grouped: dict[date, list[SlotWindow]] = defaultdict(list)
    for slot in slots:
        for window in slot_windows(slot, tz):
            grouped[window[0].date()].append(window)
    return grouped
