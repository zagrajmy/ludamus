"""When a facilitator can run something.

Where the organizer lists time slots, the proposer picks from those: that is
their one job. Otherwise the answer is in words rather than clock times. A
proposer knows they are free on Friday evening; they do not know, and should
not have to guess, that the organizer will open the room at 18:30. So the
fallback is named parts of a day, and the hours behind each part are fixed here
rather than typed in by whoever is filling the form.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING, NamedTuple

from pydantic import BaseModel

from ludamus.pacts.event import TimeSlotDTO
from ludamus.pacts.sessions import PROGRAMME_DAY_STARTS_AT_HOUR

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

# The small hours belong to the evening they grew out of. Hours are counted
# from the programme day's own midnight, which is why night runs 24-30 rather
# than 0-6.
_HOURS_PER_DAY = 24


class DayPart(StrEnum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"


class PartHours(NamedTuple):
    """The hours a part covers, counted from its programme day's midnight."""

    opens: int
    closes: int


DAY_PART_HOURS: dict[DayPart, PartHours] = {
    DayPart.MORNING: PartHours(6, 12),
    DayPart.AFTERNOON: PartHours(12, 18),
    DayPart.EVENING: PartHours(18, 24),
    DayPart.NIGHT: PartHours(24, 30),
}

# The order a day reads in, which is also the order the chips are offered in.
DAY_PARTS: tuple[DayPart, ...] = (
    DayPart.MORNING,
    DayPart.AFTERNOON,
    DayPart.EVENING,
    DayPart.NIGHT,
)


_SLOT_VALUE_PREFIX = "slot:"


class AvailabilityDTO(BaseModel):
    """One time the facilitator offered: a part of a day, or a time slot.

    `day` is the programme day either way, so offers group by day whatever
    their kind.
    """

    day: date
    offer: DayPart | TimeSlotDTO


def programme_date(moment: datetime, tz: tzinfo) -> date:
    """Say which programme day an instant belongs to.

    Returns:
        The date whose day holds the instant: 02:00 on Saturday is still
        Friday's programme.
    """
    local = moment.astimezone(tz)
    return (local - timedelta(hours=PROGRAMME_DAY_STARTS_AT_HOUR)).date()


def part_of(moment: datetime, tz: tzinfo) -> DayPart:
    """Which named part of its programme day an instant falls in.

    Returns:
        The part whose hours contain the instant.
    """
    local = moment.astimezone(tz)
    if (hour := local.hour) < PROGRAMME_DAY_STARTS_AT_HOUR:
        hour += _HOURS_PER_DAY
    for part in DAY_PARTS:
        hours = DAY_PART_HOURS[part]
        if hours.opens <= hour < hours.closes:
            return part
    return DayPart.NIGHT


def part_window(day: date, part: DayPart, tz: tzinfo) -> tuple[datetime, datetime]:
    """Resolve a part of a programme day to real instants.

    Returns:
        Its start and end, as aware datetimes.
    """
    midnight = datetime.combine(day, time(0), tzinfo=tz)
    hours = DAY_PART_HOURS[part]
    return (
        midnight + timedelta(hours=hours.opens),
        midnight + timedelta(hours=hours.closes),
    )


def offered_parts_by_day(
    *, start: datetime, end: datetime, tz: tzinfo
) -> list[tuple[date, list[DayPart]]]:
    """Which parts each programme day of an event can actually hold.

    An event that closes at 18:00 has no evening to offer, so it does not ask
    about one. Days with nothing to offer are left out entirely.

    Returns:
        Each programme day in order, with the parts its hours reach.
    """
    if end <= start:
        return []
    first = programme_date(start, tz)
    last = programme_date(end, tz)
    offered: list[tuple[date, list[DayPart]]] = []
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        parts = [
            part
            for part in DAY_PARTS
            if _overlaps((start, end), part_window(day, part, tz))
        ]
        if parts:
            offered.append((day, parts))
    return offered


def slot_availability(slot: TimeSlotDTO, tz: tzinfo) -> AvailabilityDTO:
    """Offer one of the event's time slots.

    Returns:
        The slot as an offered time, filed under the programme day it opens on.
    """
    return AvailabilityDTO(day=programme_date(slot.start_time, tz), offer=slot)


def offered_times(
    *, start: datetime, end: datetime, slots: Sequence[TimeSlotDTO], tz: tzinfo
) -> list[AvailabilityDTO]:
    """Everything a proposer can pick when they say when they could host.

    The event's time slots where it lists any, otherwise the parts of each
    programme day its hours reach.

    Returns:
        The offered times in the order a day reads in.
    """
    if slots:
        return [slot_availability(slot, tz) for slot in sorted(slots, key=_opens)]
    return [
        AvailabilityDTO(day=day, offer=part)
        for day, parts in offered_parts_by_day(start=start, end=end, tz=tz)
        for part in parts
    ]


def offered_window(entry: AvailabilityDTO, tz: tzinfo) -> tuple[datetime, datetime]:
    """Resolve an offered time to real instants.

    Returns:
        Its start and end, as aware datetimes.
    """
    if isinstance(offer := entry.offer, TimeSlotDTO):
        return offer.start_time, offer.end_time
    return part_window(entry.day, offer, tz)


def in_reading_order(
    entries: Iterable[AvailabilityDTO], tz: tzinfo
) -> list[AvailabilityDTO]:
    """Order offered times the way a day reads, whatever their kind.

    Returns:
        The times sorted by when each opens.
    """
    return sorted(entries, key=partial(offered_window, tz=tz))


def availability_value(entry: AvailabilityDTO) -> str:
    """Encode one offered time as a single form value.

    Returns:
        `slot:<pk>` for a time slot; otherwise the day and part joined, e.g.
        `2026-10-09:evening`.
    """
    if isinstance(offer := entry.offer, TimeSlotDTO):
        return f"{_SLOT_VALUE_PREFIX}{offer.pk}"
    return f"{entry.day.isoformat()}:{offer}"


def pick_offered(
    raws: Iterable[str], offered: Sequence[AvailabilityDTO]
) -> list[AvailabilityDTO]:
    """Read back the times a form sent, keeping only the ones on offer.

    A value naming another event's slot, or a part the event's hours do not
    reach, is not on offer, so it is dropped rather than trusted.

    Returns:
        The picked offered times, in the order they were offered.
    """
    picked = set(raws)
    return [entry for entry in offered if availability_value(entry) in picked]


def group_by_day(
    entries: Iterable[AvailabilityDTO],
) -> list[tuple[date, list[AvailabilityDTO]]]:
    """Gather offered times under their programme day.

    Returns:
        Each day that has any, in order, with its times in the order given.
    """
    grouped: dict[date, list[AvailabilityDTO]] = {}
    for entry in entries:
        grouped.setdefault(entry.day, []).append(entry)
    return sorted(grouped.items())


def _opens(slot: TimeSlotDTO) -> tuple[datetime, datetime]:
    return slot.start_time, slot.end_time


def _overlaps(
    first: tuple[datetime, datetime], second: tuple[datetime, datetime]
) -> bool:
    return first[0] < second[1] and second[0] < first[1]
