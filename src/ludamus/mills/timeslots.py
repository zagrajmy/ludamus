"""Shared local-day window helpers for chronology mills and schedule gates.

Time slots are proposer availability windows ("when could you run your
session?"), not schedule display units — rendered timetables show the real
session start and end times instead. Both need the same interval math, split
on a day boundary: local midnight for slots, the programme's own turnover
(specs.chronology.PROGRAMME_DAY_STARTS_AT) for the rendered schedule.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING

from ludamus.specs.chronology import PROGRAMME_DAY_STARTS_AT

if TYPE_CHECKING:
    from ludamus.pacts import TimeSlotDTO

type SlotWindow = tuple[datetime, datetime]


def _day_offset(day_starts_at: time) -> timedelta:
    return timedelta(hours=day_starts_at.hour, minutes=day_starts_at.minute)


def local_date(
    instant: datetime, *, tz: tzinfo, day_starts_at: time = time.min
) -> date:
    # The date whose day, opening at `day_starts_at`, holds the instant: at
    # 02:00 on a Saturday whose days turn at 06:00, that is still Friday.
    return (instant.astimezone(tz) - _day_offset(day_starts_at)).date()


def interval_windows(
    *, start: datetime, end: datetime, tz: tzinfo, day_starts_at: time = time.min
) -> list[SlotWindow]:
    # An interval spanning multiple local days contributes one (start, end)
    # window to each day it touches, clamped to that day's range — a day being
    # the 24 hours from `day_starts_at`. One definition of "a day", shared by
    # slots and by scheduled items.
    local_start = start.astimezone(tz)
    local_end = end.astimezone(tz)
    first_date = local_date(start, tz=tz, day_starts_at=day_starts_at)
    last_date = local_date(end, tz=tz, day_starts_at=day_starts_at)
    windows: list[SlotWindow] = []
    for offset in range((last_date - first_date).days + 1):
        cursor_date = first_date + timedelta(days=offset)
        day_start = datetime.combine(cursor_date, day_starts_at, tzinfo=tz)
        day_end = datetime.combine(
            cursor_date + timedelta(days=1), day_starts_at, tzinfo=tz
        )
        window_start = max(local_start, day_start, key=datetime.timestamp)
        window_end = min(local_end, day_end, key=datetime.timestamp)
        if window_start.timestamp() < window_end.timestamp():
            windows.append((window_start, window_end))
    return windows


def programme_windows(
    *, start: datetime, end: datetime, tz: tzinfo
) -> list[SlotWindow]:
    return interval_windows(
        start=start, end=end, tz=tz, day_starts_at=PROGRAMME_DAY_STARTS_AT
    )


def programme_date(instant: datetime, tz: tzinfo) -> date:
    return local_date(instant, tz=tz, day_starts_at=PROGRAMME_DAY_STARTS_AT)


def programme_day_start(day: date, tz: tzinfo) -> datetime:
    # The instant a programme day opens: its name and date are the day's.
    return datetime.combine(day, PROGRAMME_DAY_STARTS_AT, tzinfo=tz)


def programme_day_start_hour() -> int:
    # For the client: the fold script decides which days are already over, and
    # has to turn its days over where the server does.
    return PROGRAMME_DAY_STARTS_AT.hour


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
