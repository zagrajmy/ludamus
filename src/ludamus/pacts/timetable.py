from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.sessions import SessionDTO, SessionStatus
from ludamus.pacts.venues import SpaceDTO

if TYPE_CHECKING:
    from ludamus.pacts.event import (
        EventRepositoryProtocol,
        TimeSlotDTO,
        TimeSlotRepositoryProtocol,
    )
    from ludamus.pacts.facilitators import FacilitatorDTO
    from ludamus.pacts.proposal_categories import ProposalCategoryDTO
    from ludamus.pacts.sessions import SessionRepositoryProtocol
    from ludamus.pacts.tracks import TrackRepositoryProtocol
    from ludamus.pacts.venues import SpaceRepositoryProtocol


class PlacementRejection(StrEnum):
    NAIVE_DATETIME = "naive_datetime"
    END_NOT_AFTER_START = "end_not_after_start"
    SESSION_NOT_ACCEPTED = "session_not_accepted"
    BEFORE_PUBLICATION = "before_publication"


class PlacementRejectedError(Exception):
    def __init__(self, reason: PlacementRejection, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass
class TimetableRepos:
    events: EventRepositoryProtocol
    sessions: SessionRepositoryProtocol
    agenda_items: AgendaItemRepositoryProtocol
    spaces: SpaceRepositoryProtocol
    time_slots: TimeSlotRepositoryProtocol
    tracks: TrackRepositoryProtocol
    schedule_change_logs: ScheduleChangeLogRepositoryProtocol


@dataclass
class UnscheduledSessionsDTO:
    sessions: list[UnscheduledSessionDTO]
    has_more: bool


@dataclass
class TimetableSessionDetailDTO:
    session: SessionDTO
    agenda_item: AgendaItemDTO | None
    facilitators: list[FacilitatorDTO]
    time_slots: list[TimeSlotDTO]


@dataclass
class TimetableChangeLogDTO:
    logs: list[ScheduleChangeLogDTO]
    spaces: list[SpaceDTO]
    # The newest change per session: only those may be undone.
    revertible_pks: set[int]


class TimetableServiceProtocol(Protocol):
    def space_filter_options(self, event_pk: int) -> list[MultiselectOptionDTO]: ...
    def list_categories(self, event_pk: int) -> list[ProposalCategoryDTO]: ...
    def list_unscheduled(
        self, *, event_pk: int, filters: UnscheduledSessionFilter
    ) -> UnscheduledSessionsDTO: ...
    def session_detail(
        self, *, event_pk: int, session_pk: int
    ) -> TimetableSessionDetailDTO: ...
    def change_log(
        self, *, event_pk: int, space_pk: int | None
    ) -> TimetableChangeLogDTO: ...
    def build_grid(
        self,
        *,
        event_pk: int,
        tz: tzinfo,
        space_page: int = 1,
        filters: TimetableGridFilter | None = None,
    ) -> TimetableGridDTO: ...
    def assign_session(
        self,
        *,
        session_pk: int,
        placement: SessionPlacement,
        event_pk: int,
        user_pk: int | None = None,
    ) -> None: ...
    def unassign_session(
        self, *, session_pk: int, event_pk: int, user_pk: int | None = None
    ) -> int: ...
    def revert_change(
        self, *, log_pk: int, event_pk: int, user_pk: int | None = None
    ) -> None: ...


class ConflictDetectionServiceProtocol(Protocol):
    def detect_for_assignment(
        self, event_pk: int, session_pk: int
    ) -> list[ConflictDTO]: ...
    def list_all_for_track(
        self, event_pk: int, track_pk: int | None
    ) -> list[ConflictDTO]: ...
    def list_grid_warnings(
        self,
        *,
        event_pk: int,
        track_pk: int | None,
        items: list[AgendaItemDTO],
        spaces: list[SpaceDTO],
    ) -> tuple[list[ConflictDTO], list[PreferredSlotViolationDTO]]: ...
    def list_preferred_slot_violations(
        self, event_pk: int, track_pk: int | None
    ) -> list[PreferredSlotViolationDTO]: ...


class TimetableOverviewServiceProtocol(Protocol):
    def get_all_conflicts(self, event_pk: int) -> list[ConflictDTO]: ...
    def build_heatmap(
        self, *, event_pk: int, tz: tzinfo, conflicts: list[ConflictDTO] | None = None
    ) -> HeatmapDTO: ...
    def all_conflicts_grouped(
        self, event_pk: int, conflicts: list[ConflictDTO] | None = None
    ) -> dict[str, list[ConflictDTO]]: ...
    def track_progress(self, event_pk: int) -> list[TrackProgressDTO]: ...
    def capacity_hours(self, event_pk: int) -> CapacityHoursDTO: ...


UNSCHEDULED_LIST_LIMIT = 20


class UnscheduledSessionDTO(BaseModel):
    """Session accepted but not yet placed in the timetable."""

    pk: int
    title: str
    facilitator_name: str
    category_name: str
    category_pk: int | None
    duration_minutes: int
    participants_limit: int


class UnscheduledSessionFilter(BaseModel):
    track_pk: int | None = None
    search: str | None = None
    max_duration_minutes: int | None = None
    category_pk: int | None = None
    available_on: date | None = None
    facilitator_pks: set[int] = set()


class AgendaItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    end_time: datetime
    pk: int
    schedule_confirmed: bool
    start_time: datetime
    space_id: int = 0
    space_name: str = ""
    session_id: int = 0
    session_title: str = ""
    session_description: str = ""
    presenter_name: str = ""
    session_duration_minutes: int = 0
    session_participants_limit: int = 0
    session_status: SessionStatus | None = None
    category_name: str | None = None
    category_id: int | None = None
    session_min_age: int = 0


class AgendaItemData(TypedDict):
    end_time: datetime
    session_confirmed: bool
    session_id: int
    space_id: int
    start_time: datetime


class AgendaItemUpdateData(TypedDict, total=False):
    end_time: datetime
    session_confirmed: bool
    space_id: int
    start_time: datetime


class ConfirmationCountsRow(TypedDict):
    """One aggregate row: who or what, and its confirmed-of-scheduled counts.

    `key` is the grouping id — organizer id (None when nobody claimed the
    facilitators) or track pk.
    """

    key: int | None
    name: str
    facilitator_count: int
    scheduled_count: int
    confirmed_count: int


class ConfirmationTotalsRow(TypedDict):
    scheduled_count: int
    confirmed_count: int


class ConfirmationFacilitatorRow(TypedDict):
    pk: int
    display_name: str
    slug: str
    organizer_id: int | None
    organizer_name: str


class ConfirmationSessionRow(TypedDict):
    """One (facilitator, session) pair, flattened for the confirmations page.

    Agenda-item columns are None for a session with no place in the timetable.
    """

    facilitator_pk: int
    session_pk: int
    title: str
    status: SessionStatus
    contact_email: str
    category_name: str
    is_scheduled: bool
    is_confirmed: bool
    start_time: datetime | None
    end_time: datetime | None
    room_name: str


class AgendaItemRepositoryProtocol(Protocol):
    @staticmethod
    def create(agenda_item_data: AgendaItemData) -> None: ...
    @staticmethod
    def read(pk: int) -> AgendaItemDTO: ...
    @staticmethod
    def list_by_event(
        event_pk: int,
        *,
        facilitator_pks: set[int] | None = None,
        public_only: bool = False,
    ) -> list[AgendaItemDTO]: ...
    @staticmethod
    def list_by_track(
        track_pk: int,
        *,
        facilitator_pks: set[int] | None = None,
        public_only: bool = False,
    ) -> list[AgendaItemDTO]: ...
    @staticmethod
    def read_by_session(session_pk: int) -> AgendaItemDTO | None: ...
    @staticmethod
    def list_overlapping_in_space(
        space_pk: int,
        start_time: datetime,
        end_time: datetime,
        exclude_session_pk: int | None = None,
    ) -> list[AgendaItemDTO]: ...
    @staticmethod
    def update(pk: int, data: AgendaItemUpdateData) -> None: ...
    @staticmethod
    def count_confirmations_by_track(event_pk: int) -> list[ConfirmationCountsRow]: ...
    @staticmethod
    def count_event_totals(event_pk: int) -> ConfirmationTotalsRow: ...
    @staticmethod
    def count_without_facilitator(
        event_pk: int, track_pk: int | None = None
    ) -> int: ...
    @staticmethod
    def delete(pk: int) -> None: ...


class ScheduleChangeAction(StrEnum):
    ASSIGN = auto()
    UNASSIGN = auto()
    REVERT = auto()


class ScheduleChangeLogData(TypedDict, total=False):
    event_id: int
    session_id: int
    user_id: int | None
    action: str
    old_space_id: int | None
    new_space_id: int | None
    old_start_time: datetime | None
    old_end_time: datetime | None
    new_start_time: datetime | None
    new_end_time: datetime | None
    moved_from_id: int | None


class ScheduleChangeLogDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    event_id: int
    session_id: int
    session_title: str
    user_id: int | None
    user_name: str
    action: ScheduleChangeAction
    old_space_id: int | None
    old_space_name: str | None
    new_space_id: int | None
    new_space_name: str | None
    old_start_time: datetime | None
    old_end_time: datetime | None
    new_start_time: datetime | None
    new_end_time: datetime | None
    creation_time: datetime
    # The unassign row this assign row replaced, when the two were one move.
    moved_from_id: int | None
    acknowledgement_time: datetime | None
    acknowledged_by_name: str
    important: bool


class ScheduleChangeLogRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: ScheduleChangeLogData) -> int: ...

    @staticmethod
    def read(pk: int) -> ScheduleChangeLogDTO: ...

    @staticmethod
    def list_by_event(
        event_pk: int, *, space_pk: int | None = None
    ) -> list[ScheduleChangeLogDTO]: ...

    @staticmethod
    def list_since(event_pk: int, since: datetime) -> list[ScheduleChangeLogDTO]: ...

    @staticmethod
    def list_erratum_rows(
        *, event_pk: int, since: datetime, log_pks: list[int]
    ) -> list[ScheduleChangeLogDTO]: ...

    @staticmethod
    def set_acknowledged(
        *, event_pk: int, log_pks: list[int], user_id: int, acknowledged: bool
    ) -> None: ...

    @staticmethod
    def set_important(
        *, event_pk: int, log_pks: list[int], important: bool
    ) -> None: ...

    @staticmethod
    def list_by_session(session_id: int) -> list[ScheduleChangeLogDTO]: ...

    @staticmethod
    def latest_pks_by_session(event_pk: int) -> dict[int, int]: ...

    @staticmethod
    def latest_pk_for_session(event_pk: int, session_id: int) -> int | None: ...


type SessionPositionState = Literal["normal", "conflict", "slot_violation"]


class SessionPositionDTO(BaseModel):
    agenda_item: AgendaItemDTO
    start_minutes: int
    # How tall the block is on this day's column. A session crossing midnight
    # is clipped to the day it is drawn on and drawn again on the next; its
    # real length is `agenda_item.session_duration_minutes`.
    duration_minutes: int
    lane_start_pct: float = 0.0
    lane_width_pct: float = 100.0
    # What the block is warning about, resolved once here so the grid stops
    # testing the same session against two page-wide sets in four places.
    state: SessionPositionState = "normal"


class TimeLabelDTO(BaseModel):
    time: datetime
    offset_minutes: int


class ClosedRangeDTO(BaseModel):
    # A stretch of the day's axis no time slot covers. A drop there is
    # accepted and widens the day, so the grid greys it instead of refusing it.
    start_minutes: int
    duration_minutes: int


class SpaceColumnDTO(BaseModel):
    space: SpaceDTO
    sessions: list[SessionPositionDTO] = []


class SpaceGroupDTO(BaseModel):
    # One header cell spanning the leaf columns that share an immediate parent.
    # parent_pk None / empty name means the leaves are top-level (no parent).
    parent_pk: int | None
    parent_name: str
    span: int


class TimetableDayGridDTO(BaseModel):
    date: date
    columns: list[SpaceColumnDTO]
    event_start_iso: str
    # Each day owns its time axis. Sharing one grid-wide axis would stretch
    # every column to the union of the days, and a session split at midnight
    # puts 00:00 on one day and 24:00 on the one before -- a full 24 hours,
    # mostly empty, on every day of the event.
    total_minutes: int
    time_labels: list[TimeLabelDTO]
    closed_ranges: list[ClosedRangeDTO]


class MultiselectOptionDTO(BaseModel):
    # One row of components/multiselect-filter.html. value/label rather than
    # pk/name because this is the component's contract, not the thing it lists:
    # spaces use `depth` to indent their tree, facilitators use `meta` for the
    # columns under the name, and each leaves the other at its default.
    value: int
    label: str
    depth: int = 0
    meta: str = ""


type DateSelection = date | Literal["all"]


class TimetableGridFilter(BaseModel):
    # What the filter bar narrows the grid by. Empty means "everything".
    track_pk: int | None = None
    date_selection: DateSelection = "all"
    space_pks: set[int] = set()
    facilitator_pks: set[int] = set()


class ConflictType(StrEnum):
    SPACE_OVERLAP = auto()
    FACILITATOR_OVERLAP = auto()
    CAPACITY_EXCEEDED = auto()


class ConflictSeverity(StrEnum):
    ERROR = auto()
    WARNING = auto()


@dataclass(frozen=True)
class SessionPlacement:
    """A space and time window a session can be scheduled into."""

    space_pk: int
    start_time: datetime
    end_time: datetime


class ConflictDTO(BaseModel):
    type: ConflictType
    severity: ConflictSeverity
    # The session that has the problem (the one being placed / examined).
    subject_session_title: str
    subject_session_pk: int
    # The other session involved in the clash (occupier / co-facilitated).
    session_title: str
    session_pk: int
    facilitator_name: str | None = None
    space_capacity: int | None = None
    session_limit: int | None = None
    track_name: str | None = None
    manager_names: list[str] = []


class TimetableGridDTO(BaseModel):
    spaces: list[SpaceDTO]
    groups: list[SpaceGroupDTO]
    days: list[TimetableDayGridDTO]
    slot_minutes: int
    snap_minutes: int
    page: int
    total_pages: int
    total_spaces: int
    # 1-based, for "Rooms 6–10 of 11".
    first_space_number: int
    last_space_number: int
    total_columns: int
    available_dates: list[date] = []
    date_selection: DateSelection = "all"
    # The clashes the cards are already coloured for. Carried with the grid so
    # the page cannot list one set of conflicts while the grid marks another.
    conflicts: list[ConflictDTO] = []


class PreferredSlotRangeDTO(BaseModel):
    start_time: datetime
    end_time: datetime


class PreferredSlotViolationDTO(BaseModel):
    session_pk: int
    session_title: str
    scheduled_start: datetime
    scheduled_end: datetime
    preferred_slots: list[PreferredSlotRangeDTO]
    track_name: str | None = None
    manager_names: list[str] = []


class HeatmapCellStatus(StrEnum):
    EMPTY = auto()
    SCHEDULED = auto()
    CONFLICT = auto()


class HeatmapCellDTO(BaseModel):
    space_pk: int
    status: HeatmapCellStatus


class HeatmapRowDTO(BaseModel):
    time: datetime
    cells: list[HeatmapCellDTO]


class HeatmapDayDTO(BaseModel):
    date: date
    rows: list[HeatmapRowDTO]


class HeatmapDTO(BaseModel):
    spaces: list[SpaceDTO]
    rows: list[HeatmapRowDTO]
    days: list[HeatmapDayDTO] = []


class TrackProgressDTO(BaseModel):
    track_pk: int
    track_name: str
    manager_names: list[str]
    accepted_count: int
    scheduled_count: int
    pending_count: int = 0
    on_hold_count: int = 0
    rejected_count: int = 0
    progress_pct: int

    @property
    def active_count(self) -> int:
        # The scheduling target: proposals still in play (not rejected / on
        # hold). Denominator of the scheduled/total ratio.
        return self.pending_count + self.accepted_count

    @property
    def unassigned_count(self) -> int:
        return self.accepted_count - self.scheduled_count


class CapacityHoursDTO(BaseModel):
    room_count: int
    slot_hours: float
    capacity_hours: float
    scheduled_hours: float
    hours_to_fill: float
    filled_pct: int
