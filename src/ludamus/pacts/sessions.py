"""Sessions: the proposal row, its write shapes and its content log."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ludamus.pacts.crowd import UserDTO
    from ludamus.pacts.event import EventDTO, TimeSlotDTO
    from ludamus.pacts.facilitators import FacilitatorDTO
    from ludamus.pacts.fields import (
        OrganizerFieldDTO,
        SessionFieldValueData,
        SessionFieldValueDTO,
    )
    from ludamus.pacts.images import UploadedFileProtocol
    from ludamus.pacts.timetable import (
        ConfirmationSessionRow,
        UnscheduledSessionDTO,
        UnscheduledSessionFilter,
    )
    from ludamus.pacts.tracks import TrackDTO, TrackSessionCountsDTO
    from ludamus.pacts.venues import SpaceOptionDTO


class SessionListItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_name: str
    creation_time: datetime
    facilitator_name: str
    is_scheduled: bool
    pk: int
    status: "SessionStatus"
    title: str
    # Only the lists that reach deleted rows set this — the facilitator detail
    # page does, because a deleted session still blocks deleting a facilitator.
    is_deleted: bool = False


class SessionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    category_id: int | None
    contact_email: str
    contact_language: str
    creation_time: datetime
    description: str
    duration: str = ""
    min_age: int
    modification_time: datetime
    participants_limit: int
    pk: int
    presenter_id: int | None
    facilitator_name: str
    slug: str
    status: SessionStatus
    title: str
    cover_image_url: str = ""
    cover_image_original_name: str = ""


class SessionStatus(StrEnum):
    PENDING = auto()
    ACCEPTED = auto()
    ON_HOLD = auto()
    REJECTED = auto()


class SessionListFilters(TypedDict, total=False):
    field_filters: dict[int, str] | None
    search: str | None
    track_pk: int | None
    multi_tracks: bool | None
    category_pk: int | None
    status: SessionStatus | None
    scheduled: bool | None
    sort: str | None


class SessionData(TypedDict, total=False):
    category_id: int | None
    contact_email: str
    contact_language: str
    cover_image: UploadedFileProtocol
    description: str
    duration: str
    event_id: int
    ident: str
    min_age: int
    participants_limit: int
    presenter_id: int | None
    schedule_confirmed: bool
    facilitator_name: str
    slug: str
    status: SessionStatus
    title: str


class SessionUpdateData(TypedDict, total=False):
    category_id: int | None
    contact_email: str
    contact_language: str
    cover_image: UploadedFileProtocol | str
    description: str
    facilitator_name: str
    duration: str
    min_age: int
    participants_limit: int
    schedule_confirmed: bool
    slug: str
    status: SessionStatus
    title: str


@dataclass
class SessionSelfEditContext:
    session: SessionDTO
    event: EventDTO
    session_fields: list[tuple[OrganizerFieldDTO, str | list[str] | bool | None]]
    facilitators: list[FacilitatorDTO]


class SessionRepositoryProtocol(Protocol):
    @staticmethod
    def create(
        session_data: SessionData,
        *,
        time_slot_ids: Iterable[int] = (),
        facilitator_ids: Iterable[int] = (),
        track_ids: Iterable[int] = (),
    ) -> int: ...
    @staticmethod
    def read(pk: int) -> SessionDTO: ...
    @staticmethod
    def read_by_event(pk: int, event_id: int) -> SessionDTO: ...
    @staticmethod
    def read_presenter(session_id: int) -> UserDTO | None: ...
    @staticmethod
    def list_confirmation_rows(
        event_pk: int, facilitator_pks: list[int]
    ) -> list[ConfirmationSessionRow]: ...
    @staticmethod
    def list_track_names_by_session(
        session_pks: list[int],
    ) -> dict[int, dict[int, str]]: ...
    @staticmethod
    def list_facilitator_names_by_session(
        session_pks: list[int],
    ) -> dict[int, dict[int, str]]: ...
    @staticmethod
    def lock(pk: int) -> None: ...
    @staticmethod
    def update(pk: int, data: SessionUpdateData) -> None: ...
    @staticmethod
    def set_schedule_confirmed_for_facilitator(
        *,
        event_pk: int,
        facilitator_pk: int,
        confirmed: bool,
        contact_email: str | None = None,
        session_pk: int | None = None,
    ) -> int: ...
    @staticmethod
    def soft_delete(pk: int) -> None: ...
    @staticmethod
    def restore(pk: int, event_pk: int) -> None: ...
    @staticmethod
    def list_deleted_by_event(event_pk: int) -> list[SessionListItemDTO]: ...
    @staticmethod
    def list_alive_pks_by_event(event_pk: int) -> list[int]: ...
    @staticmethod
    def list_by_facilitator(facilitator_id: int) -> list[SessionListItemDTO]: ...
    @staticmethod
    def read_event(session_id: int) -> EventDTO: ...
    @staticmethod
    def read_space_options(session_id: int) -> list[SpaceOptionDTO]: ...
    @staticmethod
    def read_time_slot(session_id: int, time_slot_id: int) -> TimeSlotDTO: ...
    @staticmethod
    def read_time_slots(session_id: int) -> list[TimeSlotDTO]: ...
    @staticmethod
    def count_by_category(category_id: int) -> int: ...
    @staticmethod
    def read_preferred_time_slot_ids(session_id: int) -> list[int]: ...
    @staticmethod
    def read_preferred_time_slots(session_id: int) -> list[TimeSlotDTO]: ...
    @staticmethod
    def read_preferred_time_slots_by_sessions(
        session_ids: Iterable[int],
    ) -> dict[int, list[TimeSlotDTO]]: ...
    @staticmethod
    def slug_exists(event_id: int, slug: str) -> bool: ...
    @staticmethod
    def find_id_by_ident(event_id: int, ident: str) -> int | None: ...
    @staticmethod
    def find_ids_by_title_and_email(
        *, event_id: int, title: str, contact_email: str
    ) -> list[int]: ...
    @staticmethod
    def set_ident(pk: int, ident: str) -> None: ...
    @staticmethod
    def save_field_values(
        session_id: int, values: list[SessionFieldValueData]
    ) -> None: ...
    @staticmethod
    def read_field_values(session_id: int) -> list[SessionFieldValueDTO]: ...
    @staticmethod
    def list_field_values_for_sessions(
        session_ids: list[int], field_ids: list[int]
    ) -> dict[int, dict[str, str | list[str] | bool]]: ...
    @staticmethod
    def delete_field_values_for_fields(
        session_id: int, field_ids: list[int]
    ) -> int: ...
    @staticmethod
    def list_sessions_by_event(
        event_id: int, filters: SessionListFilters | None = None
    ) -> list[SessionListItemDTO]: ...
    @staticmethod
    def read_track_ids(session_id: int) -> list[int]: ...
    @staticmethod
    def read_tracks(session_id: int) -> list[TrackDTO]: ...
    @staticmethod
    def set_session_tracks(session_pk: int, track_pks: list[int]) -> None: ...
    @staticmethod
    def set_time_slots(session_id: int, time_slot_ids: list[int]) -> None: ...
    @staticmethod
    def read_facilitators(session_id: int) -> list[FacilitatorDTO]: ...
    @staticmethod
    def read_facilitators_by_sessions(
        session_ids: Iterable[int],
    ) -> dict[int, list[FacilitatorDTO]]: ...
    @staticmethod
    def count_by_track(event_id: int) -> dict[int, TrackSessionCountsDTO]: ...
    @staticmethod
    def set_facilitators(session_id: int, facilitator_ids: list[int]) -> None: ...
    @staticmethod
    def replace_facilitators_in_sessions(
        source_ids: list[int], target_id: int
    ) -> None: ...
    @staticmethod
    def list_unscheduled_by_event(
        event_pk: int, filters: UnscheduledSessionFilter
    ) -> tuple[list[UnscheduledSessionDTO], bool]: ...


ContentFieldValue = str | int | bool | list[str] | None


class ContentFieldChange(TypedDict):
    # Identity only — no display text. `field` is the core-column key
    # (e.g. "title"); for dynamic session fields it is "" and `field_id`
    # holds the SessionField id. Labels are resolved per-request at render.
    field: str
    field_id: int | None
    old: ContentFieldValue
    new: ContentFieldValue


class ContentChangeLogData(TypedDict):
    event_id: int
    session_id: int
    user_id: int | None
    changes: list[ContentFieldChange]


@dataclass(frozen=True)
class SessionContentEditData:
    # The write payload for a single session content edit. `facilitator_ids`
    # None leaves the assignment untouched; a list (possibly empty) replaces it.
    # `field_values` None leaves dynamic answers untouched (partial POST guard).
    # `remove_field_ids` drops answers to fields the session's category no
    # longer asks for — the only edit the panel allows on those.
    update: SessionUpdateData
    field_values: list[SessionFieldValueData] | None = None
    facilitator_ids: list[int] | None = None
    track_ids: list[int] | None = None
    time_slot_ids: list[int] | None = None
    remove_field_ids: list[int] | None = None


class ContentChangeLogDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    event_id: int
    session_id: int
    session_title: str
    user_id: int | None
    user_name: str
    changes: list[ContentFieldChange]
    creation_time: datetime

    @property
    def item_name(self) -> str:
        # What the shared change-log table shows for "which thing changed",
        # whichever kind of log it is rendering.
        return self.session_title


class ContentChangeLogRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: ContentChangeLogData) -> None: ...

    @staticmethod
    def read(pk: int) -> ContentChangeLogDTO: ...

    @staticmethod
    def list_by_event(event_pk: int) -> list[ContentChangeLogDTO]: ...

    @staticmethod
    def latest_pks_by_session(event_pk: int) -> dict[int, int]: ...

    @staticmethod
    def latest_pk_for_session(event_pk: int, session_id: int) -> int | None: ...
