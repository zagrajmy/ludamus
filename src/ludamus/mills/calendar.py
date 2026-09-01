"""Calendar files and links for anything with a title, a time and a place."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from typing import TYPE_CHECKING
from urllib.parse import urlencode

if TYPE_CHECKING:
    from datetime import datetime

PRODID = "-//Zagrajmy//Ludamus//PL"


@dataclass(frozen=True)
class CalendarEntry:
    """One dated thing, in the shape every calendar target asks for.

    A caller that wants a default length for an open-ended entry sets `end`
    itself: an entry without one prints no DTEND, and the web calendars fall
    back to a zero-length event.
    """

    uid: str
    title: str
    start: datetime
    url: str
    end: datetime | None = None
    location: str = ""
    description: str = ""


def ics_escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def ics_utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def ics_document(entry: CalendarEntry, *, stamped_at: datetime) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "BEGIN:VEVENT",
        f"UID:{entry.uid}",
        f"DTSTAMP:{ics_utc(stamped_at)}",
        f"DTSTART:{ics_utc(entry.start)}",
    ]
    if entry.end:
        lines.append(f"DTEND:{ics_utc(entry.end)}")
    lines.append(f"SUMMARY:{ics_escape(entry.title)}")
    if entry.location:
        lines.append(f"LOCATION:{ics_escape(entry.location)}")
    if entry.description:
        lines.append(f"DESCRIPTION:{ics_escape(entry.description)}")
    lines += [f"URL:{entry.url}", "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


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
