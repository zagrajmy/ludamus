"""Event integrations: imports and ticketing behind one implementation registry."""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.fields import SessionFieldType

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.propose import ImportRow


class IntegrationKind(StrEnum):
    IMPORT = "import"
    TICKETING = "ticketing"
    EXPORT = "export"


class IntegrationImplementationId(StrEnum):
    GOOGLE_PROPOSAL_PULLER = "google-proposal-puller"
    KONWENCIK_SHEET_PUSHER = "konwencik-sheet-pusher"
    SKLEP_KAPITULARZ = "sklep-kapitularz"


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
    field_type: SessionFieldType = "text"
    is_multiple: bool = False
    allow_custom: bool = False
    options: list[str] = []


class IntegrationImplementation(Protocol):
    # What every integration shares, whichever way the data flows: which kind
    # it serves, the shape of its per-event config, and a credential probe the
    # panel can run. Everything provider-specific (auth header format, response
    # payload shape) stays behind the kind-specific subprotocols below.
    kind: IntegrationKind
    config_model: type[BaseModel]

    def check(self, secret: bytes, config: BaseModel) -> CheckResult: ...


class ImportIntegrationImplementation(IntegrationImplementation, Protocol):
    # An integration proposals can be pulled from. Kept apart from the base so
    # an exporter does not carry three dead stubs, and so mypy rejects one
    # being registered as a source.
    def fetch_questions(
        self, *, secret: bytes, config: BaseModel, header_row: int = 1
    ) -> list[SourceQuestion]: ...
    def fetch_headers(
        self, *, secret: bytes, config: BaseModel, header_row: int = 1
    ) -> list[str]: ...
    def fetch_responses(
        self, *, secret: bytes, config: BaseModel, header_row: int = 1
    ) -> list[ImportRow]: ...


class TicketingIntegrationImplementation(IntegrationImplementation, Protocol):
    def fetch_membership_count(
        self, *, secret: bytes, config: BaseModel, user_email: str
    ) -> int: ...


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
    last_run_json: str = "{}"


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
    def update_last_run(*, event_id: int, pk: int, last_run_json: str) -> None: ...
    @staticmethod
    def get_for_update(event_id: int, pk: int) -> EventIntegrationDTO: ...
    @staticmethod
    def list_by_kind(
        kind: IntegrationKind, *, event_ended_after: datetime
    ) -> list[EventIntegrationDTO]: ...
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
