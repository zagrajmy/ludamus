"""The days and hours a schedule grid covers, derived from the event.

Nothing here is stored: the event's own start and end give the opening guess,
and whatever is already scheduled widens it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING

from ludamus.pacts.sessions import MIDNIGHT

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ludamus.pacts.sessions import Window


@dataclass(frozen=True)
class OpeningHours:
    """Which days a schedule draws, and the clock window every day shares."""

    dates: list[date]
    # Minutes from local midnight. One window for every day, so a given clock
    # hour sits on the same row whichever day you read across.
    span: tuple[int, int]


def _minutes_into_day(moment: datetime, day: date, tz: tzinfo) -> float:
    midnight = datetime.combine(day, time(0), tzinfo=tz)
    return (moment.astimezone(tz) - midnight).total_seconds() / 60


def _clock_minutes(moment: datetime, tz: tzinfo, *, closing: bool) -> float:
    local = moment.astimezone(tz)
    minutes = local.hour * 60 + local.minute
    # Midnight closes the day it ends rather than opening the next one, so an
    # event finishing at 00:00 reads as 24:00 instead of collapsing the span.
    # An event that OPENS at midnight means 00:00, so only the closing edge
    # gets the wrap.
    if closing and minutes == 0:
        return 24 * 60
    return minutes


def event_opening_hours(
    *,
    start: datetime,
    end: datetime,
    occupied: Iterable[Window],
    tz: tzinfo,
    snap_minutes: int,
    extend_before_hours: int = 0,
    extend_after_hours: int = 0,
) -> OpeningHours:
    """Work out the days and hours a schedule covers, storing nothing.

    The event's own start and end give the opening guess: a convention booked
    16:00 to 22:00 opens its grid at 16:00. Anything already scheduled widens
    it, so a session dropped at 08:00 keeps its row on every later render, and
    the extend arguments reach hours nothing occupies yet.
    """
    dates = _dates_between(MIDNIGHT.date_of(start, tz), MIDNIGHT.date_of(end, tz))
    minutes = [
        _clock_minutes(start, tz, closing=False),
        _clock_minutes(end, tz, closing=True),
    ]
    seen = set(dates)
    for window_start, window_end in occupied:
        if (day := MIDNIGHT.date_of(window_start, tz)) not in seen:
            seen.add(day)
            dates.append(day)
        minutes.extend(
            (
                _minutes_into_day(window_start, day, tz),
                _minutes_into_day(window_end, day, tz),
            )
        )
    lo = math.floor(min(minutes) / snap_minutes) * snap_minutes
    hi = math.ceil(max(minutes) / snap_minutes) * snap_minutes
    lo -= extend_before_hours * 60
    hi += extend_after_hours * 60
    lo, hi = _guard_span(int(lo), int(hi), snap_minutes)
    return OpeningHours(dates=sorted(dates), span=(lo, hi))


_DEFAULT_SPAN_MINUTES = 8 * 60
_DAY_MINUTES = 24 * 60


def _guard_span(lo: int, hi: int, snap_minutes: int) -> tuple[int, int]:
    # An event whose start and end share a clock time says nothing about its
    # hours, so give the grid a workable default rather than no height at all.
    if hi - lo < snap_minutes:
        hi = lo + _DEFAULT_SPAN_MINUTES
    lo = max(0, lo)
    hi = min(_DAY_MINUTES, hi)
    if hi - lo < snap_minutes:
        lo = max(0, hi - _DEFAULT_SPAN_MINUTES)
    return lo, hi


def _dates_between(first: date, last: date) -> list[date]:
    if last < first:
        first, last = last, first
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]
