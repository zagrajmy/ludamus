"""Time slots split into the local days they touch.

Time slots are proposer availability windows ("when could you run your
session?"), not schedule display units — rendered timetables show the real
session start and end times instead. Both need the same interval math
(`DayTurnover`), split on a day boundary: local midnight for slots, the
programme's own turnover for the rendered schedule.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from ludamus.pacts.chronology import MIDNIGHT

if TYPE_CHECKING:
    from datetime import date, tzinfo

    from ludamus.pacts.chronology import Window
    from ludamus.pacts.legacy import TimeSlotDTO


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
