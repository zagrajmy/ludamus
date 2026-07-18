"""Printing subdomain DTOs and protocols.

Read-only document shapes for organizer-facing printable materials
(per-room door cards, a printed timetable). Rendered as print-styled HTML
pages in the web gate (browser Save-as-PDF); assembled by `mills.printing`.
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


@dataclass(frozen=True)
class PrintTimetableQueryDTO:
    event_pk: int
    tz: tzinfo
    scope_space_pks: frozenset[int] | None = None
    track_pk: int | None = None
    scope_name: str | None = None
    confirmed_only: bool = False


@dataclass(frozen=True)
class DoorCardsQueryDTO:
    event_pk: int
    tz: tzinfo
    scope_space_pks: frozenset[int] | None = None
    scope_name: str | None = None
    confirmed_only: bool = False
    time_range: tuple[datetime, datetime] | None = None


@dataclass(frozen=True)
class AreaScheduleQueryDTO:
    event_pk: int
    time_range: tuple[datetime, datetime]
    scope_space_pks: frozenset[int] | None = None
    scope_name: str | None = None
    confirmed_only: bool = False


class DoorCardEntryDTO(BaseModel):
    start_time: datetime
    end_time: datetime
    session: PrintSessionDTO


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


class PrintTimetablePageDTO(BaseModel):
    day: date
    space_names: list[str]
    rows: list[PrintTimetableRowDTO]
    space_range_name: str | None = None


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


class PrintSessionListDocumentDTO(BaseModel):
    event_name: str
    event_description: str
    event_start: datetime
    event_end: datetime
    scope_name: str | None = None
    sessions: list[PrintSessionListItemDTO]


class PrintablesReminderRecipientDTO(BaseModel):
    user_id: int
    email: str


class PrintablesReminderDTO(BaseModel):
    event_pk: int
    event_name: str
    event_slug: str
    # Site domain of the owning sphere — the notifier composes the absolute
    # print-materials link from it (sphere sites live on different domains).
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
    def build_door_cards(self, query: DoorCardsQueryDTO) -> DoorCardsDocumentDTO: ...
    def build_timetable(
        self, query: PrintTimetableQueryDTO
    ) -> PrintTimetableDocumentDTO: ...
    def build_area_schedule(
        self, query: AreaScheduleQueryDTO
    ) -> AreaScheduleDocumentDTO: ...
    def build_session_list(
        self, event_pk: int, *, confirmed_only: bool = False
    ) -> PrintSessionListDocumentDTO | None: ...
