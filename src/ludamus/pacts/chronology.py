"""Chronology subdomain DTOs and protocols.

Currently spans the Timetable (agenda scheduling) and CFP (personal-data
field management) bounded contexts. Split per `plans/hex_refactor.md` if
the file grows past ~12 top-level members or 1000 lines.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.crowd import UserDTO
from ludamus.pacts.legacy import (
    AgendaItemDTO,
    ContentChangeLogDTO,
    EventDTO,
    LocationData,
    SessionContentEditData,
    SessionDTO,
    SessionFieldValueData,
    SessionFieldValueDTO,
    SessionParticipationStatus,
    SessionSelfEditContext,
    SpaceDTO,
    SpaceOptionDTO,
    TimeSlotDTO,
)
from ludamus.pacts.party import PartyDTO

if TYPE_CHECKING:
    from ludamus.pacts.submissions import ImportRow


class IntegrationKind(StrEnum):
    IMPORT = "import"
    TICKETING = "ticketing"


class IntegrationImplementationId(StrEnum):
    GOOGLE_PROPOSAL_PULLER = "google-proposal-puller"


class CheckOutcome(StrEnum):
    OK = "ok"
    AUTH_FAILED = "auth_failed"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"


@dataclass
class CheckResult:
    outcome: CheckOutcome
    hint: str = ""


class SourceQuestion(BaseModel):
    # A source-form question described in the importer's own vocabulary: the
    # prompt plus the field setup a new target field would inherit. Multi-choice
    # maps to `select` + `is_multiple` (the domain has no multi `checkbox`); an
    # "other"/free-text option sets `allow_custom` and is dropped from `options`.
    title: str
    field_type: Literal["text", "select", "checkbox"] = "text"
    is_multiple: bool = False
    allow_custom: bool = False
    options: list[str] = []


class IntegrationImplementation(Protocol):
    kind: IntegrationKind
    config_model: type[BaseModel]

    def check(self, secret: bytes, config: BaseModel) -> CheckResult: ...
    def fetch_questions(
        self, *, secret: bytes, config: BaseModel, header_row: int = 1
    ) -> list[SourceQuestion]: ...
    def fetch_headers(
        self, *, secret: bytes, config: BaseModel, header_row: int = 1
    ) -> list[str]: ...
    def fetch_responses(
        self, *, secret: bytes, config: BaseModel, header_row: int = 1
    ) -> list[ImportRow]: ...


class EventIntegrationDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    event_id: int
    kind: IntegrationKind
    implementation: IntegrationImplementationId
    connection_id: int
    connection_display_name: str
    display_name: str
    config_json: str
    settings_json: str
    questions_snapshot_json: str = "[]"


class EventIntegrationCreateData(TypedDict):
    kind: IntegrationKind
    implementation: IntegrationImplementationId
    connection_id: int
    display_name: str
    config_json: str


class EventIntegrationUpdateData(TypedDict):
    display_name: str
    connection_id: int
    config_json: str


@dataclass
class IntegrationCheckRequest:
    sphere_id: int
    implementation: IntegrationImplementationId
    connection_id: int
    config_json: str


class EventIntegrationsRepositoryProtocol(Protocol):
    @staticmethod
    def list_for_event(
        event_id: int, kind: IntegrationKind | None = None
    ) -> list[EventIntegrationDTO]: ...
    @staticmethod
    def get(event_id: int, pk: int) -> EventIntegrationDTO: ...
    @staticmethod
    def create(
        event_id: int, data: EventIntegrationCreateData
    ) -> EventIntegrationDTO: ...
    @staticmethod
    def update(
        event_id: int, pk: int, data: EventIntegrationUpdateData
    ) -> EventIntegrationDTO: ...
    @staticmethod
    def update_settings(
        *, event_id: int, pk: int, settings_json: str
    ) -> EventIntegrationDTO: ...
    @staticmethod
    def update_questions_snapshot(
        *, event_id: int, pk: int, questions_snapshot_json: str
    ) -> EventIntegrationDTO: ...
    @staticmethod
    def delete(event_id: int, pk: int) -> None: ...


class EventIntegrationsServiceProtocol(Protocol):
    def list_for_event(
        self, event_id: int, kind: IntegrationKind | None = None
    ) -> list[EventIntegrationDTO]: ...
    def get(self, event_id: int, pk: int) -> EventIntegrationDTO: ...
    def create(
        self, sphere_id: int, event_id: int, data: EventIntegrationCreateData
    ) -> EventIntegrationDTO: ...
    def update(
        self, sphere_id: int, event_id: int, pk: int, data: EventIntegrationUpdateData
    ) -> EventIntegrationDTO: ...
    def delete(self, event_id: int, pk: int) -> None: ...
    def fetch_questions(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[SourceQuestion]: ...
    def get_cached_questions(self, event_id: int, pk: int) -> list[SourceQuestion]: ...
    def populate_questions_snapshot(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[SourceQuestion]: ...
    def refetch_questions(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[SourceQuestion]: ...
    def import_missing_questions(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> tuple[list[SourceQuestion], int]: ...
    def fetch_responses(
        self, *, sphere_id: int, event_id: int, pk: int
    ) -> list[ImportRow]: ...
    def save_settings(self, *, event_id: int, pk: int, settings_json: str) -> None: ...
    def check(self, request: IntegrationCheckRequest) -> CheckResult: ...
    def list_implementations(
        self, kind: IntegrationKind
    ) -> dict[IntegrationImplementationId, IntegrationImplementation]: ...
    def list_all_implementations(
        self,
    ) -> dict[IntegrationImplementationId, IntegrationImplementation]: ...


class SessionSelfEditServiceProtocol(Protocol):
    def get_edit_context(
        self, session_id: int, user_id: int | None
    ) -> SessionSelfEditContext: ...
    def update(
        self,
        session_id: int,
        user_id: int | None,
        cleaned_data: dict[str, object],
        field_values: list[SessionFieldValueData] | None,
    ) -> None: ...


class ContentChangeNotLatestError(Exception):
    """Only the latest content change for a session may be reverted."""


class ContentChangeNotRevertibleError(Exception):
    """Every entry in the change is irreversible (cover image, assignments)."""


class SessionContentEditServiceProtocol(Protocol):
    def apply(
        self,
        *,
        session_id: int,
        event_id: int,
        user_id: int | None,
        data: SessionContentEditData,
    ) -> None: ...
    def revert(self, *, event_pk: int, log_pk: int, user_pk: int | None) -> None: ...
    def list_log(self, event_id: int) -> list[ContentChangeLogDTO]: ...
    def list_field_names(self, event_id: int) -> dict[int, str]: ...
    def revertible_log_pks(self, event_id: int) -> set[int]: ...


class SessionConfirmationServiceProtocol(Protocol):
    def set_session_confirmed(
        self, event_pk: int, agenda_item_pk: int, *, confirmed: bool
    ) -> None: ...
    def confirm_all(self, event_pk: int) -> None: ...
    def confirm_block(self, event_pk: int, track_pk: int) -> None: ...


class SessionDeletionServiceProtocol(Protocol):
    def soft_delete(
        self, event_pk: int, session_pk: int, user_pk: int | None = None
    ) -> None: ...
    def restore(self, event_pk: int, session_pk: int) -> None: ...


class ProposalScheduledError(Exception):
    """Scheduled proposals may only be accepted, never demoted."""


class ProposalStatusServiceProtocol(Protocol):
    def mark_pending(self, *, event_pk: int, session_pk: int) -> None: ...
    def mark_accepted(self, *, event_pk: int, session_pk: int) -> None: ...
    def mark_on_hold(self, *, event_pk: int, session_pk: int) -> None: ...
    def mark_rejected(self, *, event_pk: int, session_pk: int) -> None: ...


class SpaceTimeConflictError(Exception):
    """Another session already occupies that space during the chosen slot."""


class ProposalAcceptDeniedError(Exception):
    """Only sphere managers and superusers may accept proposals."""


class ProposalAcceptContextDTO(BaseModel):
    session: SessionDTO
    event: EventDTO
    presenter: UserDTO | None
    space_options: list[SpaceOptionDTO]
    time_slots: list[TimeSlotDTO]
    preferred_time_slot_ids: list[int]
    field_values: list[SessionFieldValueDTO]
    can_accept: bool


class ProposalAcceptanceServiceProtocol(Protocol):
    def get_accept_context(
        self, *, session_id: int, user_slug: str, sphere_id: int
    ) -> ProposalAcceptContextDTO | None: ...
    def accept_session(
        self,
        *,
        session_id: int,
        space_id: int,
        time_slot_id: int,
        user_slug: str,
        sphere_id: int,
    ) -> None: ...


class PartySessionSeatDTO(BaseModel):
    user: UserDTO
    status: SessionParticipationStatus
    creation_time: datetime


class SessionCardStatsDTO(BaseModel):
    enrolled_count: int
    waiting_count: int
    is_full: bool
    is_enrollment_available: bool
    effective_participants_limit: int
    full_participant_info: str


class PartySessionHistoryDTO(SessionCardStatsDTO):
    session: SessionDTO
    agenda_item: AgendaItemDTO
    presenter: UserDTO | None
    participations: list[PartySessionSeatDTO]
    location: LocationData
    viewer_enrolled: bool


class PartyEventHistoryDTO(BaseModel):
    event_pk: int
    event_name: str
    event_slug: str
    sessions: list[PartySessionHistoryDTO]


class PartyDetailDTO(BaseModel):
    party: PartyDTO
    history: list[PartyEventHistoryDTO]


class PartySessionHistoryRepositoryProtocol(Protocol):
    @staticmethod
    def list_for_party(
        *, party_pk: int, viewer_pk: int
    ) -> list[PartyEventHistoryDTO]: ...


class PartySessionHistoryServiceProtocol(Protocol):
    def read_detail(
        self, *, party_pk: int, viewer_pk: int
    ) -> PartyDetailDTO | None: ...


class SessionModalSeatDTO(BaseModel):
    user: UserDTO
    status: SessionParticipationStatus
    creation_time: datetime


class SessionModalDTO(SessionCardStatsDTO):
    session: SessionDTO
    agenda_item: AgendaItemDTO
    presenter: UserDTO | None
    participations: list[SessionModalSeatDTO]
    location: LocationData
    field_values: list[SessionFieldValueDTO]
    viewer_enrolled: bool
    viewer_waiting: bool
    can_edit: bool
    is_ongoing: bool
    is_ended: bool


class SessionModalRepositoryProtocol(Protocol):
    @staticmethod
    def read_modal(
        *,
        event_id: int,
        session_id: int,
        viewer_user_ids: list[int],
        editor_user_id: int | None,
    ) -> SessionModalDTO | None: ...


class SessionModalServiceProtocol(Protocol):
    def read(
        self,
        *,
        event_id: int,
        session_id: int,
        viewer_user_ids: list[int],
        editor_user_id: int | None,
    ) -> SessionModalDTO | None: ...


TIMETABLE_ROOM_PAGE_SIZE = 5
TIMETABLE_SLOT_MINUTES = 60
TIMETABLE_SNAP_MINUTES = 5


class SessionPositionDTO(BaseModel):
    agenda_item: AgendaItemDTO
    start_minutes: int
    duration_minutes: int
    lane_start_pct: float = 0.0
    lane_width_pct: float = 100.0


class TimeLabelDTO(BaseModel):
    time: datetime
    offset_minutes: int


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


type DateSelection = date | Literal["all"]


class TimetableGridDTO(BaseModel):
    spaces: list[SpaceDTO]
    groups: list[SpaceGroupDTO]
    days: list[TimetableDayGridDTO]
    time_labels: list[TimeLabelDTO]
    total_minutes: int
    slot_minutes: int
    snap_minutes: int
    page: int
    total_pages: int
    total_spaces: int
    available_dates: list[date] = []
    date_selection: DateSelection = "all"


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
