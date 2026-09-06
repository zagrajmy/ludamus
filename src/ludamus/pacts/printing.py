"""Printing subdomain DTOs and protocols.

Read-only document shapes for the printable materials on the public
``/print`` page: a timetable grid, per-room-and-day door cards, per-space
descriptions pages, and the participants' session list. Rendered as
print-styled HTML pages in the web gate (browser Save-as-PDF); assembled by
`mills.printing`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Protocol

from pydantic import BaseModel


class PrintOptionDTO(BaseModel):
    pk: int
    name: str
    slug: str


class PrintSessionDTO(BaseModel):
    title: str
    presenter_name: str


# One query shape for every printable document; a builder ignores the fields
# its document doesn't use (door cards take no track, the area schedule no tz).
@dataclass(frozen=True)
class PrintQueryDTO:
    event_pk: int
    tz: tzinfo
    scope_space_pks: frozenset[int] | None = None
    track_pk: int | None = None
    scope_name: str | None = None
    # Confirmed-only is the safe default: unconfirmed sessions reach paper
    # only when a caller deliberately asks for them.
    confirmed_only: bool = True
    # None means the whole event; the mills default to the event bounds.
    time_range: tuple[datetime, datetime] | None = None


class DoorCardEntryDTO(BaseModel):
    start_time: datetime
    end_time: datetime
    session: PrintSessionDTO


# One card is one sheet of paper: it hangs on a door for a single day.
class DoorCardDTO(BaseModel):
    space_name: str
    capacity: int | None
    day: date
    entries: list[DoorCardEntryDTO]


class DoorCardsDocumentDTO(BaseModel):
    event_name: str
    event_description: str
    event_start: datetime
    event_end: datetime
    # Venue or area name when the document is scoped; None for the whole event.
    scope_name: str | None = None
    cards: list[DoorCardDTO]


# The grid the page draws, rooms across and time down like the event page's
# rooms view: a row is a stretch of the day's axis between two instants at
# which the programme changes, and a tile is one session starting on a row
# and spanning every row it covers. Rows and columns are 1-based.
class PrintTimetableRowDTO(BaseModel):
    start_time: datetime
    end_time: datetime

    @property
    def minutes(self) -> int:
        return round((self.end_time - self.start_time).total_seconds() / 60)


class PrintTimetableTileDTO(BaseModel):
    session: PrintSessionDTO
    start_time: datetime
    end_time: datetime
    col: int
    row: int
    span: int


class PrintTimetablePageDTO(BaseModel):
    day: date
    space_names: list[str]
    rows: list[PrintTimetableRowDTO]
    tiles: list[PrintTimetableTileDTO]
    space_range_name: str | None = None

    @property
    def spans(self) -> list[int]:
        # The distinct tile heights: the template serves one rule per span
        # length it actually uses, as _room_lanes.html does.
        return sorted({tile.span for tile in self.tiles})


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
    pages: list[PrintTimetablePageDTO]


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


class PrintSessionListItemDTO(BaseModel):
    title: str
    presenter_name: str
    description: str
    start_time: datetime
    end_time: datetime
    space_name: str


# The participants' program: every session of the event in time order, with
# the room — what one carries around the venue.
class PrintSessionListDocumentDTO(BaseModel):
    event_name: str
    event_description: str
    event_start: datetime
    event_end: datetime
    sessions: list[PrintSessionListItemDTO]


class PrintablesReminderRecipientDTO(BaseModel):
    user_id: int
    email: str


class PrintablesReminderDTO(BaseModel):
    event_pk: int
    event_name: str
    event_slug: str
    # Site domain of the owning sphere — the notifier composes the absolute
    # print-page link from it (sphere sites live on different domains).
    sphere_domain: str
    recipients: list[PrintablesReminderRecipientDTO]


class PrintablesReadyNotification(BaseModel):
    recipient_user_id: int
    recipient_email: str
    event_name: str
    event_slug: str
    sphere_domain: str


class PrintablesReminderRepositoryProtocol(Protocol):
    @staticmethod
    def list_pending_reminders(
        *, now: datetime, lead_time: timedelta
    ) -> list[PrintablesReminderDTO]: ...
    @staticmethod
    def mark_printed(event_pk: int) -> None: ...
    @staticmethod
    def mark_reminder_sent(event_pk: int, *, at: datetime) -> None: ...


class PrintablesNotifierProtocol(Protocol):
    def notify_printables_ready(
        self, notification: PrintablesReadyNotification
    ) -> None: ...


class PrintablesReminderServiceProtocol(Protocol):
    def mark_printed(self, event_pk: int) -> None: ...
    def send_due_reminders(self, *, now: datetime) -> int: ...


class PrintMaterialsServiceProtocol(Protocol):
    def list_tracks(self, event_pk: int) -> list[PrintOptionDTO]: ...
    def build_door_cards(self, query: PrintQueryDTO) -> DoorCardsDocumentDTO: ...
    def build_timetable(self, query: PrintQueryDTO) -> PrintTimetableDocumentDTO: ...
    def build_area_schedule(self, query: PrintQueryDTO) -> AreaScheduleDocumentDTO: ...
    def build_session_list(
        self, query: PrintQueryDTO
    ) -> PrintSessionListDocumentDTO: ...
