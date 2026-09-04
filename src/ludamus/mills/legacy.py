from __future__ import annotations

import string
from dataclasses import replace
from datetime import UTC, datetime
from secrets import choice as _secret_choice
from typing import TYPE_CHECKING

import markdown as _md
import nh3

from ludamus.mills.calendar import CalendarEntry, ics_document
from ludamus.mills.calendar import google_calendar_url as google_calendar_link
from ludamus.mills.calendar import outlook_calendar_url as outlook_calendar_link
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


def _entry(encounter: EncounterDTO, url: str) -> CalendarEntry:
    return CalendarEntry(
        uid=f"{encounter.share_code}@ludamus",
        title=encounter.title,
        start=encounter.start_time,
        end=encounter.end_time,
        url=url,
        location=encounter.place or "",
        description=encounter.description or "",
    )


def generate_ics_content(encounter: EncounterDTO, url: str) -> str:
    return ics_document(_entry(encounter, url), stamped_at=datetime.now(tz=UTC))


def _dated_entry(encounter: EncounterDTO, url: str) -> CalendarEntry:
    entry = _entry(encounter, url)
    if entry.end:
        return entry
    return replace(entry, end=entry.start + ENCOUNTER_DEFAULT_DURATION)


def google_calendar_url(encounter: EncounterDTO, url: str) -> str:
    return google_calendar_link(_dated_entry(encounter, url))


def outlook_calendar_url(encounter: EncounterDTO, url: str) -> str:
    return outlook_calendar_link(_dated_entry(encounter, url))


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
