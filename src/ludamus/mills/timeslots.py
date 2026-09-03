"""Shared local-day window helpers for chronology mills and schedule gates.

Time slots are proposer availability windows ("when could you run your
session?"), not schedule display units — rendered timetables show the real
session start and end times instead. Both need the same interval math, split
on a day boundary: local midnight for slots, the programme's own turnover
(specs.chronology.PROGRAMME_DAY_STARTS_AT_HOUR) for the rendered schedule.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING

from ludamus.specs.chronology import PROGRAMME_DAY_STARTS_AT_HOUR

if TYPE_CHECKING:
    from ludamus.pacts import TimeSlotDTO

type Window = tuple[datetime, datetime]


def local_date(*, instant: datetime, tz: tzinfo, day_start_hour: int = 0) -> date:
    # The date whose day, opening at `day_start_hour`, holds the instant: at
    # 02:00 on a Saturday whose days turn at 06:00, that is still Friday.
    return (instant.astimezone(tz) - timedelta(hours=day_start_hour)).date()


def day_opening(*, day: date, tz: tzinfo, day_start_hour: int = 0) -> datetime:
    return datetime.combine(day, time(day_start_hour), tzinfo=tz)


def interval_windows(
    *, start: datetime, end: datetime, tz: tzinfo, day_start_hour: int = 0
) -> list[Window]:
    # An interval spanning multiple local days contributes one (start, end)
    # window to each day it touches, clamped to that day's range — a day being
    # the 24 hours from `day_start_hour`. One definition of "a day", shared by
    # slots and by scheduled items.
    local_start = start.astimezone(tz)
    local_end = end.astimezone(tz)
    first_date = local_date(instant=start, tz=tz, day_start_hour=day_start_hour)
    last_date = local_date(instant=end, tz=tz, day_start_hour=day_start_hour)
    windows: list[Window] = []
    for offset in range((last_date - first_date).days + 1):
        cursor_date = first_date + timedelta(days=offset)
        day_start = day_opening(day=cursor_date, tz=tz, day_start_hour=day_start_hour)
        day_end = day_opening(
            day=cursor_date + timedelta(days=1), tz=tz, day_start_hour=day_start_hour
        )
        window_start = max(local_start, day_start, key=datetime.timestamp)
        window_end = min(local_end, day_end, key=datetime.timestamp)
        if window_start.timestamp() < window_end.timestamp():
            windows.append((window_start, window_end))
    return windows


def programme_windows(*, start: datetime, end: datetime, tz: tzinfo) -> list[Window]:
    return interval_windows(
        start=start, end=end, tz=tz, day_start_hour=PROGRAMME_DAY_STARTS_AT_HOUR
    )


def programme_date(instant: datetime, tz: tzinfo) -> date:
    return local_date(
        instant=instant, tz=tz, day_start_hour=PROGRAMME_DAY_STARTS_AT_HOUR
    )


def programme_day_start(day: date, tz: tzinfo) -> datetime:
    # The instant a programme day opens: its name and date are the day's.
    return day_opening(day=day, tz=tz, day_start_hour=PROGRAMME_DAY_STARTS_AT_HOUR)


def programme_day_start_hour() -> int:
    # For the client: the fold script decides which days are already over, and
    # has to turn its days over where the server does.
    return PROGRAMME_DAY_STARTS_AT_HOUR


def slot_windows(slot: TimeSlotDTO, tz: tzinfo) -> list[Window]:
    return interval_windows(start=slot.start_time, end=slot.end_time, tz=tz)


def slot_windows_by_local_date(
    slots: list[TimeSlotDTO], tz: tzinfo
) -> dict[date, list[Window]]:
    grouped: dict[date, list[Window]] = defaultdict(list)
    for slot in slots:
        for window in slot_windows(slot, tz):
            grouped[window[0].date()].append(window)
    return grouped
