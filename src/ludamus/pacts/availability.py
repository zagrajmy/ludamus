"""When a facilitator can run something, in words rather than clock times.

A proposer knows they are free on Friday evening. They do not know, and should
not have to guess, that the organizer will open the room at 18:30. So
availability is answered in named parts of a day, and the hours behind each
part are fixed here rather than typed in by whoever is filling the form.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from enum import StrEnum
from typing import NamedTuple

from pydantic import BaseModel

# A convention day ends when people go to sleep, not at midnight, so the small
# hours belong to the evening they grew out of. Hours are counted from the
# programme day's own midnight, which is why night runs 24-30 rather than 0-6.
PROGRAMME_DAY_STARTS_AT_HOUR = 6
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


class AvailabilityDTO(BaseModel):
    """One part of one programme day the facilitator offered."""

    day: date
    part: DayPart


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


def availability_value(day: date, part: DayPart) -> str:
    """Encode one offered pair as a single form value.

    Returns:
        The day and part joined, e.g. `2026-10-09:evening`.
    """
    return f"{day.isoformat()}:{part.value}"


def availability_from_value(raw: str) -> AvailabilityDTO | None:
    """Read back a pair a form sent.

    Returns:
        The pair, or None when the text does not spell one.
    """
    day, _, part = raw.partition(":")
    try:
        return AvailabilityDTO(day=date.fromisoformat(day), part=DayPart(part))
    except ValueError:
        return None


def _overlaps(
    first: tuple[datetime, datetime], second: tuple[datetime, datetime]
) -> bool:
    return first[0] < second[1] and second[0] < first[1]
