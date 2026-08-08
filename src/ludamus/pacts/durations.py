"""The stored shape of a session length.

`Session.duration` and `ProposalCategory.durations` hold ISO 8601 durations.
That format is a storage detail every writer normalizes into and every reader
leaves: it must not reach a screen, organizer's or participant's.
"""

import re

MINUTES_PER_HOUR = 60
_CANONICAL_DURATION_RE = re.compile(r"PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?")
_DURATION_PART_RE = re.compile(r"(?P<hours>\d+)\s*h|(?P<minutes>\d+)\s*m")


def parse_duration(iso_duration: str) -> tuple[int, int]:
    if not (match := _CANONICAL_DURATION_RE.fullmatch(iso_duration or "")):
        return 0, 0
    return int(match["hours"] or 0), int(match["minutes"] or 0)


def build_duration(*, hours: int, minutes: int) -> str:
    if not hours and not minutes:
        return ""
    return "PT" + (f"{hours}H" if hours else "") + (f"{minutes}M" if minutes else "")


def normalize_duration(text: str) -> str:
    # Durations arrive in whatever shape their author felt like — "P4H",
    # "50min", "110m". Read every hour and minute part out of the text and
    # rebuild canonically; text carrying neither normalizes to "" (unset).
    hours = minutes = 0
    for part in _DURATION_PART_RE.finditer((text or "").lower()):
        hours += int(part.group("hours") or 0)
        minutes += int(part.group("minutes") or 0)
    carried, minutes = divmod(minutes, MINUTES_PER_HOUR)
    return build_duration(hours=hours + carried, minutes=minutes)
