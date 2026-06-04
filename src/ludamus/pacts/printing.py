"""Printing subdomain DTOs and protocols.

Read-only document shapes for organizer-facing printable materials
(per-room door cards, a printed timetable). Rendered as print-styled HTML
pages in the web gate (browser Save-as-PDF); assembled by `mills.printing`.
"""

from __future__ import annotations

from datetime import date, datetime, tzinfo
from typing import Protocol

from pydantic import BaseModel


class PrintSessionDTO(BaseModel):
    title: str
    presenter_name: str


class DoorCardEntryDTO(BaseModel):
    start_time: datetime
    end_time: datetime
    # None marks an empty time slot, rendered as a visible gap on the card.
    session: PrintSessionDTO | None


class DoorCardDayDTO(BaseModel):
    day: date
    entries: list[DoorCardEntryDTO]


class DoorCardDTO(BaseModel):
    space_name: str
    capacity: int | None
    days: list[DoorCardDayDTO]


class DoorCardsDocumentDTO(BaseModel):
    event_name: str
    event_description: str
    event_start: datetime
    event_end: datetime
    # Venue or area name when the document is scoped; None for the whole event.
    scope_name: str | None = None
    cards: list[DoorCardDTO]


class PrintTimetableCellDTO(BaseModel):
    # Empty list marks a slot with no session in this space (a visible gap).
    sessions: list[PrintSessionDTO]


class PrintTimetableRowDTO(BaseModel):
    start_time: datetime
    end_time: datetime
    cells: list[PrintTimetableCellDTO]


class PrintTimetableDayDTO(BaseModel):
    day: date
    space_names: list[str]
    rows: list[PrintTimetableRowDTO]


class PrintTimetableDocumentDTO(BaseModel):
    event_name: str
    event_description: str
    event_start: datetime
    event_end: datetime
    # Venue or area name when the document is scoped; None for the whole event.
    scope_name: str | None = None
    # True when every scheduled session is confirmed (nothing pending) and at
    # least one is scheduled — i.e. the printed grid is the whole program. Drives
    # the public print page's QR label: a partial program points people online.
    is_complete: bool = False
    days: list[PrintTimetableDayDTO]


class AreaScheduleSessionDTO(BaseModel):
    title: str
    presenter_name: str
    description: str
    start_time: datetime
    end_time: datetime


class AreaScheduleSpaceDTO(BaseModel):
    space_name: str
    capacity: int | None
    sessions: list[AreaScheduleSessionDTO]


class AreaScheduleDocumentDTO(BaseModel):
    # Per-space pages covering a time range, with full session descriptions —
    # the room you walk into, with enough text to decide whether to sit down.
    event_name: str
    event_description: str
    event_start: datetime
    event_end: datetime
    range_start: datetime
    range_end: datetime
    scope_name: str | None = None
    spaces: list[AreaScheduleSpaceDTO]


class PrintMaterialsServiceProtocol(Protocol):
    def build_door_cards(
        self,
        event_pk: int,
        tz: tzinfo,
        *,
        area_pks: frozenset[int] | None = None,
        scope_name: str | None = None,
        confirmed_only: bool = False,
    ) -> DoorCardsDocumentDTO: ...
    def build_timetable(
        self,
        event_pk: int,
        tz: tzinfo,
        *,
        area_pks: frozenset[int] | None = None,
        scope_name: str | None = None,
        confirmed_only: bool = False,
    ) -> PrintTimetableDocumentDTO: ...
    def build_area_schedule(
        self,
        event_pk: int,
        time_range: tuple[datetime, datetime],
        *,
        area_pks: frozenset[int] | None = None,
        scope_name: str | None = None,
        confirmed_only: bool = False,
    ) -> AreaScheduleDocumentDTO: ...
