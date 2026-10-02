"""Calendar links for anything with a title, a time and a place."""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from ludamus.pacts.calendar import ics_utc

if TYPE_CHECKING:
    from ludamus.pacts.calendar import CalendarEntry


def _details(entry: CalendarEntry) -> str:
    return f"{entry.description}\n\n{entry.url}" if entry.description else entry.url


def google_calendar_url(entry: CalendarEntry) -> str:
    end = entry.end or entry.start
    params = {
        "action": "TEMPLATE",
        "text": entry.title,
        "dates": f"{ics_utc(entry.start)}/{ics_utc(end)}",
        "details": _details(entry),
    }
    if entry.location:
        params["location"] = entry.location
    return f"https://calendar.google.com/calendar/render?{urlencode(params)}"


def outlook_calendar_url(entry: CalendarEntry) -> str:
    end = entry.end or entry.start
    params = {
        "rru": "addevent",
        "subject": entry.title,
        "startdt": entry.start.astimezone(UTC).isoformat(),
        "enddt": end.astimezone(UTC).isoformat(),
        "body": _details(entry),
    }
    if entry.location:
        params["location"] = entry.location
    return f"https://outlook.live.com/calendar/0/action/compose?{urlencode(params)}"
