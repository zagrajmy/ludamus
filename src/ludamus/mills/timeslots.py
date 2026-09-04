"""Day-window helpers for chronology mills and schedule gates.

Time slots are proposer availability windows ("when could you run your
session?"), not schedule display units — rendered timetables show the real
session start and end times instead. Both need the same interval math, split
on a day boundary: local midnight for slots, the programme's own turnover for
the rendered schedule.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING

from ludamus.pacts.chronology import PROGRAMME_DAY_STARTS_AT_HOUR

if TYPE_CHECKING:
    from ludamus.pacts import TimeSlotDTO

type Window = tuple[datetime, datetime]


@dataclass(frozen=True)
class DayTurnover:
    # Where a day begins: the hour, local to the event, at which one day ends
    # and the next opens. Everything that asks "which day is this instant on"
    # asks the same turnover, so the answers agree.
    hour: int

    def date_of(self, instant: datetime, tz: tzinfo) -> date:
        # The date whose day holds the instant: at 02:00 on a Saturday whose
        # days turn at 06:00, that is still Friday. Wall-clock arithmetic on
        # purpose — a clock change that night moves the turnover with it.
        return (instant.astimezone(tz) - timedelta(hours=self.hour)).date()

    def opening(self, day: date, tz: tzinfo) -> datetime:
        # The instant the day opens: its name and date are the day's.
        return datetime.combine(day, time(self.hour), tzinfo=tz)

    def windows(self, *, start: datetime, end: datetime, tz: tzinfo) -> list[Window]:
        # An interval spanning multiple days contributes one (start, end)
        # window to each day it touches, clamped to that day's 24 hours.
        local_start = start.astimezone(tz)
        local_end = end.astimezone(tz)
        first_date = self.date_of(start, tz)
        last_date = self.date_of(end, tz)
        windows: list[Window] = []
        for offset in range((last_date - first_date).days + 1):
            cursor_date = first_date + timedelta(days=offset)
            day_start = self.opening(cursor_date, tz)
            day_end = self.opening(cursor_date + timedelta(days=1), tz)
            window_start = max(local_start, day_start, key=datetime.timestamp)
            window_end = min(local_end, day_end, key=datetime.timestamp)
            if window_start.timestamp() < window_end.timestamp():
                windows.append((window_start, window_end))
        return windows


MIDNIGHT = DayTurnover(0)
PROGRAMME_DAYS = DayTurnover(PROGRAMME_DAY_STARTS_AT_HOUR)


def slot_windows(slot: TimeSlotDTO, tz: tzinfo) -> list[Window]:
    return MIDNIGHT.windows(start=slot.start_time, end=slot.end_time, tz=tz)


def slot_windows_by_local_date(
    slots: list[TimeSlotDTO], tz: tzinfo
) -> dict[date, list[Window]]:
    grouped: dict[date, list[Window]] = defaultdict(list)
    for slot in slots:
        for window in slot_windows(slot, tz):
            grouped[MIDNIGHT.date_of(window[0], tz)].append(window)
    return grouped
