"""Shared time-slot helpers for the chronology and printing mills."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ludamus.pacts import TimeSlotDTO

type SlotWindow = tuple[datetime, datetime]


def slot_windows_by_local_date(
    slots: list[TimeSlotDTO], tz: tzinfo
) -> dict[date, list[SlotWindow]]:
    # A slot spanning multiple local dates contributes one (start, end) window
    # to each date it touches, clamped to that date's [00:00, 24:00) range.
    grouped: dict[date, list[SlotWindow]] = defaultdict(list)
    for slot in slots:
        local_start = slot.start_time.astimezone(tz)
        local_end = slot.end_time.astimezone(tz)
        days_span = (local_end.date() - local_start.date()).days + 1
        for offset in range(days_span):
            cursor_date = local_start.date() + timedelta(days=offset)
            day_start = datetime.combine(cursor_date, datetime.min.time(), tzinfo=tz)
            day_end = day_start + timedelta(days=1)
            window_start = max(local_start, day_start)
            window_end = min(local_end, day_end)
            if window_start < window_end:
                grouped[cursor_date].append((window_start, window_end))
    return grouped
