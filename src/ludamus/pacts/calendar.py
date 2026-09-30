"""iCalendar text for anything with a title, a time and a place.

Pure formatting, shared by the ``.ics`` downloads and the invites that mail
an entry straight into an attendee's calendar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

PRODID = "-//Zagrajmy//Ludamus//PL"
_MAX_LINE_OCTETS = 75


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


class InviteMethod(StrEnum):
    REQUEST = "REQUEST"
    CANCEL = "CANCEL"


@dataclass(frozen=True)
class Mailbox:
    name: str
    email: str


@dataclass(frozen=True)
class CalendarInvite:
    """What turns a calendar file into an iTIP message (RFC 5546).

    Mail clients add a REQUEST to the calendar on arrival and drop the event
    on a CANCEL with the same UID; of two messages for one UID, the higher
    `sequence` wins.
    """

    method: InviteMethod
    sequence: int
    organizer: Mailbox
    attendee: Mailbox


def ics_escape(text: str) -> str:
    # NOTE: browsers submit textareas with CRLF; a bare CR left in a content
    # line splits it on the wire.
    return (
        text.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def ics_utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _param_text(text: str) -> str:
    # NOTE: a parameter value cannot carry a DQUOTE or a line break, even
    # escaped (RFC 5545 §3.1).
    cleaned = text.replace('"', "'").replace("\r", " ").replace("\n", " ")
    return f'"{cleaned}"'


def _fold(line: str) -> str:
    # NOTE: RFC 5545 caps content lines at 75 octets and strict parsers
    # (Outlook) reject longer ones. Continuations start with a space.
    chunks: list[str] = []
    current = ""
    limit = _MAX_LINE_OCTETS
    for char in line:
        if len((current + char).encode()) > limit:
            chunks.append(current)
            current = ""
            limit = _MAX_LINE_OCTETS - 1
        current += char
    chunks.append(current)
    return "\r\n ".join(chunks)


def _invite_lines(invite: CalendarInvite) -> list[str]:
    status = "CANCELLED" if invite.method is InviteMethod.CANCEL else "CONFIRMED"
    attendee = invite.attendee
    return [
        f"SEQUENCE:{invite.sequence}",
        f"STATUS:{status}",
        (
            f"ORGANIZER;CN={_param_text(invite.organizer.name)}"
            f":mailto:{invite.organizer.email}"
        ),
        (
            f"ATTENDEE;CN={_param_text(attendee.name or attendee.email)}"
            ";ROLE=REQ-PARTICIPANT;PARTSTAT=ACCEPTED;RSVP=FALSE"
            f":mailto:{attendee.email}"
        ),
    ]


def ics_document(
    entry: CalendarEntry, *, stamped_at: datetime, invite: CalendarInvite | None = None
) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}"]
    if invite:
        lines.append(f"METHOD:{invite.method}")
    lines += [
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
    lines.append(f"URL:{entry.url}")
    if invite:
        lines += _invite_lines(invite)
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
