from __future__ import annotations

import string
from datetime import UTC, datetime
from secrets import choice as _secret_choice
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import markdown as _md
import nh3

from ludamus.specs.encounter import ENCOUNTER_DEFAULT_DURATION

_BASE62_CHARS = string.ascii_letters + string.digits


def generate_share_code(length: int = 6) -> str:
    return "".join(_secret_choice(_BASE62_CHARS) for _ in range(length))


_MARKDOWN_ALLOWED_TAGS = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "ul",
}
_MARKDOWN_ALLOWED_ATTRIBUTES = {"a": {"href", "title"}, "abbr": {"title"}}


def render_markdown(text: str) -> str:
    result: str = _md.markdown(  # type: ignore [misc]
        text, extensions=["nl2br", "fenced_code"]
    )
    return nh3.clean(
        result, tags=_MARKDOWN_ALLOWED_TAGS, attributes=_MARKDOWN_ALLOWED_ATTRIBUTES
    )


def generate_ics_content(encounter: EncounterDTO, url: str) -> str:
    def _ics_dt(dt: datetime) -> str:
        utc = dt.astimezone(UTC)
        return utc.strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Ludamus//Encounters//EN",
        "BEGIN:VEVENT",
        f"DTSTART:{_ics_dt(encounter.start_time)}",
    ]
    if encounter.end_time:
        lines.append(f"DTEND:{_ics_dt(encounter.end_time)}")
    lines.append(f"SUMMARY:{encounter.title}")
    if encounter.place:
        lines.append(f"LOCATION:{encounter.place}")
    if encounter.description:
        escaped = encounter.description.replace("\\", "\\\\").replace("\n", "\\n")
        lines.append(f"DESCRIPTION:{escaped}")
    lines.extend(
        [
            f"URL:{url}",
            f"UID:{encounter.share_code}@ludamus",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )
    return "\r\n".join(lines)


def _gcal_dt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def google_calendar_url(encounter: EncounterDTO, url: str) -> str:
    end = encounter.end_time or (encounter.start_time + ENCOUNTER_DEFAULT_DURATION)
    params = {
        "action": "TEMPLATE",
        "text": encounter.title,
        "dates": f"{_gcal_dt(encounter.start_time)}/{_gcal_dt(end)}",
        "details": (
            f"{encounter.description}\n\n{url}" if encounter.description else url
        ),
    }
    if encounter.place:
        params["location"] = encounter.place
    return f"https://calendar.google.com/calendar/render?{urlencode(params)}"


def outlook_calendar_url(encounter: EncounterDTO, url: str) -> str:
    end = encounter.end_time or (encounter.start_time + ENCOUNTER_DEFAULT_DURATION)
    params = {
        "rru": "addevent",
        "subject": encounter.title,
        "startdt": encounter.start_time.astimezone(UTC).isoformat(),
        "enddt": end.astimezone(UTC).isoformat(),
        "body": f"{encounter.description}\n\n{url}" if encounter.description else url,
    }
    if encounter.place:
        params["location"] = encounter.place
    return f"https://outlook.live.com/calendar/0/action/compose?{urlencode(params)}"


if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts import (
        DateTimeRangeProtocol,
        EncounterDTO,
        EventDTO,
        UnitOfWorkProtocol,
    )


class PanelService:
    """Service for backoffice panel business logic."""

    def __init__(self, uow: UnitOfWorkProtocol) -> None:
        self._uow = uow

    def delete_session_field(self, field_pk: int) -> bool:
        """Delete a session field if not used by session types.

        Args:
            field_pk: The field primary key.

        Returns:
            True if deleted, False if field has requirements.
        """
        if self._uow.session_fields.has_requirements(field_pk):
            return False
        self._uow.session_fields.delete(field_pk)
        return True

    def delete_time_slot(self, time_slot_pk: int) -> bool:
        """Delete a time slot if not used in any proposals.

        Args:
            time_slot_pk: The time slot primary key.

        Returns:
            True if deleted, False if time slot has proposals.
        """
        if self._uow.time_slots.has_proposals(time_slot_pk):
            return False
        self._uow.time_slots.delete(time_slot_pk)
        return True

    @staticmethod
    def validate_time_slot(
        start: datetime,
        end: datetime,
        event: EventDTO,
        existing_slots: Sequence[DateTimeRangeProtocol],
    ) -> list[str]:
        errors: list[str] = []

        if start >= end:
            errors.append("Start must be before end.")

        if start < event.start_time or end > event.end_time:
            errors.append("Time slot must be within event dates.")

        for slot in existing_slots:
            if start < slot.end_time and end > slot.start_time:
                errors.append("Time slot overlaps with an existing slot.")
                break

        return errors
