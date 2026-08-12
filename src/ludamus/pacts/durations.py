from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

MINUTES_PER_HOUR = 60
MAX_DURATION_HOURS = 23
MAX_DURATION_MINUTES = 59

_CANONICAL_DURATION_RE = re.compile(r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?")
_LOOSE_DURATION_RE = re.compile(
    r"p?t?\s*(?:(?P<hours>\d+)\s*h(?:ours?|rs?)?)?"
    r"\s*(?:(?P<minutes>\d+)\s*m(?:inutes?|ins?)?)?"
)


class InvalidDurationError(ValueError):
    pass


def parse_duration(iso_duration: str | None) -> tuple[int, int]:
    if not (match := _CANONICAL_DURATION_RE.fullmatch(iso_duration or "")):
        return 0, 0
    return int(match["hours"] or 0), int(match["minutes"] or 0)


def parse_duration_part(raw: str, *, maximum: int) -> int:
    if not (text := (raw or "").strip()):
        return 0
    if not text.isdigit() or len(text) > len(str(maximum)) or int(text) > maximum:
        raise InvalidDurationError
    return int(text)


def stepper_parts(iso: str) -> tuple[str, str]:
    hours, minutes = parse_duration(iso)
    return (str(hours) if hours else "", str(minutes) if minutes else "")


def duration_from_parts(*, hours: str, minutes: str) -> str:
    return build_duration(
        hours=parse_duration_part(hours, maximum=MAX_DURATION_HOURS),
        minutes=parse_duration_part(minutes, maximum=MAX_DURATION_MINUTES),
    )


def build_duration(*, hours: int, minutes: int) -> str:
    carried, minutes = divmod(minutes, MINUTES_PER_HOUR)
    hours += carried
    if not hours and not minutes:
        return ""
    return "PT" + (f"{hours}H" if hours else "") + (f"{minutes}M" if minutes else "")


def normalize_duration(text: str) -> str:
    if not (match := _LOOSE_DURATION_RE.fullmatch((text or "").strip().lower())):
        return ""
    return build_duration(
        hours=int(match["hours"] or 0), minutes=int(match["minutes"] or 0)
    )


def format_duration(iso_duration: str | None) -> str:
    hours, minutes = parse_duration(iso_duration)

    if hours and minutes:
        return f"{hours}h {minutes}min"
    if hours:
        return f"{hours}h"
    if minutes:
        return f"{minutes}min"
    return ""


def duration_choices(durations: Sequence[str]) -> list[tuple[str, str]]:
    return [(d, label) for d in durations if (label := format_duration(d))]
