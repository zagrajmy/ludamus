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

from ludamus.pacts.legacy import (
    AgendaItemDTO,
    ContentChangeLogDTO,
    SessionContentEditData,
    SessionFieldValueData,
    SessionSelfEditContext,
    SpaceDTO,
)

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
        self,
        *,
        secret: bytes,
        config: BaseModel,
        header_row: int = 1,
        email_column: int | None = None,
    ) -> list[SourceQuestion]: ...
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


class SessionContentEditServiceProtocol(Protocol):
    def apply(
        self,
        *,
        session_id: int,
        event_id: int,
        user_id: int | None,
        data: SessionContentEditData,
    ) -> None: ...
    def list_log(self, event_id: int) -> list[ContentChangeLogDTO]: ...
    def list_field_names(self, event_id: int) -> dict[int, str]: ...


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


TIMETABLE_ROOM_PAGE_SIZE = 5
TIMETABLE_SLOT_MINUTES = 60


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


class TimetableGridDTO(BaseModel):
    spaces: list[SpaceDTO]
    columns: list[SpaceColumnDTO]
    groups: list[SpaceGroupDTO]
    time_labels: list[TimeLabelDTO]
    total_minutes: int
    event_start_iso: str
    slot_minutes: int
    page: int
    total_pages: int
    total_spaces: int
    available_dates: list[date] = []
    selected_date: date | None = None


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
    progress_pct: int

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
