"""The stored shape of a session length.

`Session.duration` and `ProposalCategory.durations` hold ISO 8601 durations.
That format is a storage detail every writer normalizes into and every reader
leaves: it must not reach a screen, organizer's or participant's.
"""

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


def parse_duration(iso_duration: str | None) -> tuple[int, int]:
    if not (match := _CANONICAL_DURATION_RE.fullmatch(iso_duration or "")):
        return 0, 0
    return int(match["hours"] or 0), int(match["minutes"] or 0)


def build_duration(*, hours: int, minutes: int) -> str:
    carried, minutes = divmod(minutes, MINUTES_PER_HOUR)
    hours += carried
    if not hours and not minutes:
        return ""
    return "PT" + (f"{hours}H" if hours else "") + (f"{minutes}M" if minutes else "")


def normalize_duration(text: str) -> str:
    # Durations arrive in whatever shape their author felt like — "P4H",
    # "50min", "110m". Read the hour and minute parts and rebuild canonically.
    # The match is anchored: text the pattern cannot consume whole ("2h30",
    # "1.5h", "5 maja") normalizes to "" (unset) rather than to a plausible
    # guess, because a wrong length on screen is indistinguishable from a
    # right one.
    if not (match := _LOOSE_DURATION_RE.fullmatch((text or "").strip().lower())):
        return ""
    return build_duration(
        hours=int(match["hours"] or 0), minutes=int(match["minutes"] or 0)
    )


def format_duration(iso_duration: str | None) -> str:
    # Empty when the stored value is unreadable — a raw ISO string is never
    # shown, so callers guard on the label rather than on the stored value.
    hours, minutes = parse_duration(iso_duration)

    if hours and minutes:
        return f"{hours}h {minutes}min"
    if hours:
        return f"{hours}h"
    if minutes:
        return f"{minutes}min"
    return ""


def duration_choices(durations: Sequence[str]) -> list[tuple[str, str]]:
    # A duration nothing can read is left out: an option is worth offering only
    # when it can be labelled with a length.
    return [(d, label) for d in durations if (label := format_duration(d))]
