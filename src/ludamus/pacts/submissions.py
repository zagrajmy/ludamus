"""Submissions subdomain DTOs and protocols.

Owns proposal intake: the CFP configuration (personal-data fields) bounded
context today, with the Session lifecycle and proposal import to follow.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from ludamus.pacts import PersonalDataFieldValueData
    from ludamus.pacts.legacy import (
        FacilitatorChangeLogDTO,
        FacilitatorChangeLogRepositoryProtocol,
        FacilitatorListItemDTO,
        FacilitatorRepositoryProtocol,
        FacilitatorUpdateData,
        FieldUsageSummary,
        PersonalDataFieldCreateData,
        PersonalDataFieldDTO,
        PersonalDataFieldRepositoryProtocol,
        PersonalDataFieldUpdateData,
        PersonalDataFieldValueRepositoryProtocol,
        ProposalCategoryDTO,
        ProposalCategoryRepositoryProtocol,
        SessionFieldRepositoryProtocol,
        SessionRepositoryProtocol,
        TimeSlotRepositoryProtocol,
        TrackRepositoryProtocol,
    )


# --- Proposal import (mapping recipe stored as the integration's settings) ---

_DUPLICATE_HEADER_SUFFIX = re.compile(r" \([0-9]+\)")


class DuplicateValueError(Exception):
    # Raised at value-access time when a row carries conflicting non-empty
    # values across columns that collapse to the same form question. The mill
    # catches it inside `_cell` and turns it into a per-row skip — the row's
    # other targets stay intact, the import flow proceeds with the next row.
    def __init__(self, header: str, values: list[str]) -> None:
        super().__init__()
        self.header = header
        self.values = values


class ImportRow:
    # A single response row read from the source spreadsheet. Form-linked
    # sheets suffix duplicate question columns with " (2)", " (3)", ... and
    # the mill's question dedup has already collapsed those source questions
    # to one entry — so `get_value` collapses the matching columns the same
    # way at value-access time. Conflicting non-empty values surface as
    # `DuplicateValueError` so the caller (the mill) can decide what a skip
    # means; the link stays a dumb header→cell mapping.
    def __init__(self, data: dict[str, str]) -> None:
        self._data = dict(data)

    @property
    def data(self) -> dict[str, str]:
        # Read-only snapshot of the raw header→cell mapping, used to serialize
        # the row into the log entry's response_json.
        return dict(self._data)

    def get_value(self, header: str, default: str = "") -> str:
        candidates = {
            value
            for key, value in self._data.items()
            if value and _row_header_matches(key, header)
        }
        if len(candidates) > 1:
            raise DuplicateValueError(header, sorted(candidates))
        return next(iter(candidates), default)

    def has_column(self, header: str) -> bool:
        # Whether the source row carries this column at all (even when empty),
        # so a mapped question pointing at a non-existent column surfaces as an
        # error instead of a silent blank.
        return any(_row_header_matches(key, header) for key in self._data)


def _row_header_matches(key: str, header: str) -> bool:
    # Compare ignoring surrounding whitespace: a form question title, its sheet
    # column header, and the saved recipe key can disagree by a stray trailing
    # space, which would otherwise silently drop the mapping.
    key, header = key.strip(), header.strip()
    if key == header:
        return True
    suffix = key.removeprefix(header)
    return suffix != key and _DUPLICATE_HEADER_SUFFIX.fullmatch(suffix) is not None


class TimeSlotSpec(BaseModel):
    # A provisioned time-slot window; the importer dedupes by (start, end).
    to: Literal["time_slot"] = "time_slot"
    start_time: datetime
    end_time: datetime


class EntityRef(BaseModel):
    # A track or category the importer resolves by slug, provisioning it
    # (deduped by slug) with `name` when the event does not have it yet.
    name: str
    slug: str


class DurationSpec(BaseModel):
    # An operator-typed ISO 8601 duration string (e.g. "PT1H30M") that the
    # importer writes into Session.duration when the row's answer matches the
    # option this spec is keyed under.
    to: Literal["duration"] = "duration"
    iso: str


# A choice option's mapped value: a time-slot window (or several), the
# track/category entity it resolves to, or an ISO duration.
QuestionValue = TimeSlotSpec | list[TimeSlotSpec] | EntityRef | DurationSpec


class QuestionTarget(BaseModel):
    # `to` is "session.<col>" (a built-in proposal field), "field.<slug>" (a new
    # session field), "personal.<slug>" (a new personal-data field),
    # "session.time_slots" (provisioned windows), or "track"/"category"
    # (provisioned entities); each provisioned by slug from
    # `ImportSettings.definitions`; `ignore` marks a question as deliberately
    # unmapped. `values` maps a choice option's text to its target value — for
    # `session.time_slots`, one window or several; for "track"/"category", the
    # entity it resolves to. `overrides` substitutes the raw cell text before
    # any parsing or `values` lookup — used to clean up free-form answers like
    # "maybe 8, maybe 10" into "10" for a numeric target, or to fix typos in a
    # choice answer so it hits the configured `values` mapping. `catchall` is
    # the track/category that catches a custom or unmatched answer. `confirmed`
    # is the operator's per-row sign-off in the summary editor; the run gate
    # refuses to import while any mapped question is still unconfirmed.
    to: str | None = None
    ignore: bool = False
    values: dict[str, QuestionValue] = {}
    overrides: dict[str, str] = {}
    catchall: EntityRef | None = None
    confirmed: bool = False


class FieldDefinition(BaseModel):
    # Setup for a brand-new target field, keyed by its slug under
    # `FieldDefinitions`; `name` is the operator-supplied display name (the slug
    # is the match key). Multi-choice is `select` + `multiple` (the domain has
    # no multi `checkbox`); `options` is the explicit, operator-editable list.
    name: str = ""
    type: Literal["text", "select", "checkbox"] = "text"
    multiple: bool = False
    allow_custom: bool = False
    options: list[str] = []


class FieldDefinitions(BaseModel):
    personal_fields: dict[str, FieldDefinition] = {}
    session_fields: dict[str, FieldDefinition] = {}


class ImportSettings(BaseModel):
    # `header_row` is the 1-indexed sheet row whose cells become the column
    # keys for every response row (everything above it is ignored). Numbering
    # matches what the operator sees in the browser, so row 1 is the very
    # first row. Sheets produced straight by Google Forms have headers in
    # row 1; sheets with a branding / instructions banner at the top push
    # them down.
    # `unique_key_columns` names the column headers whose values together
    # identify a row across re-fetches; retry uses them to locate the row
    # again even after the operator deletes or rearranges rows in the source.
    # `sheet_headers` caches the source sheet's header row, refreshed whenever
    # the questions snapshot is. Both the recipe and `unique_key_columns` are
    # chosen from it: the form schema alone can't offer the metadata columns
    # (timestamp, auto-collected email), whose wording follows the form's
    # locale, so those are mapped like any other column.
    questions: dict[str, QuestionTarget] = {}
    definitions: FieldDefinitions = Field(default_factory=FieldDefinitions)
    header_row: int = 1
    unique_key_columns: list[str] = []
    sheet_headers: list[str] = []


class AccreditationType(StrEnum):
    NONE = "none"
    STANDARD = "standard"
    GUEST = "guest"
    HONORARY = "honorary"


class ImportLogStatus(StrEnum):
    SUCCESS = "success"
    SKIPPED = "skipped"


class ImportLogEntryDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    integration_id: int
    row_index: int
    status: ImportLogStatus
    reason: str = ""
    response_json: str = "{}"
    title: str = ""
    display_name: str = ""
    session_id: int | None = None
    attempted_at: datetime


class ImportLogEntryCreateData(BaseModel):
    integration_id: int
    row_index: int
    status: ImportLogStatus
    reason: str = ""
    response_json: str = "{}"
    title: str = ""
    display_name: str = ""
    session_id: int | None = None


class ImportLogEntryRepositoryProtocol(Protocol):
    @staticmethod
    def upsert(data: ImportLogEntryCreateData) -> ImportLogEntryDTO: ...
    @staticmethod
    def list_for_integration(
        integration_pk: int, *, status: ImportLogStatus | None = None, search: str = ""
    ) -> list[ImportLogEntryDTO]: ...
    @staticmethod
    def for_session(session_pk: int) -> ImportLogEntryDTO | None: ...
    @staticmethod
    def read(pk: int) -> ImportLogEntryDTO: ...


@dataclass
class ProposalImportResult:
    created: int
    fields_created: int
    skipped: int = 0
    duplicates: int = 0


@dataclass
class ValueDelta:
    added: int = 0
    removed: int = 0


@dataclass
class ApplyFieldLayoutResult:
    sessions_processed: int = 0
    session_field_values: ValueDelta = field(default_factory=ValueDelta)
    personal_entries: ValueDelta = field(default_factory=ValueDelta)
    session_fields_pruned: int = 0
    personal_fields_pruned: int = 0
    session_builtins_filled: int = 0
    session_links_filled: int = 0


@dataclass(frozen=True)
class ImportRepos:  # pylint: disable=too-many-instance-attributes
    """The repos the proposal importer creates proposals and provisions into."""

    sessions: SessionRepositoryProtocol
    session_fields: SessionFieldRepositoryProtocol
    personal_fields: PersonalDataFieldRepositoryProtocol
    personal_data_field_values: PersonalDataFieldValueRepositoryProtocol
    time_slots: TimeSlotRepositoryProtocol
    tracks: TrackRepositoryProtocol
    categories: ProposalCategoryRepositoryProtocol
    facilitators: FacilitatorRepositoryProtocol
    log_entries: ImportLogEntryRepositoryProtocol


class ProposalImportServiceProtocol(Protocol):
    def run(
        self, *, sphere_id: int, event_id: int, integration_pk: int
    ) -> ProposalImportResult: ...
    def run_sample(
        self, *, sphere_id: int, event_id: int, integration_pk: int
    ) -> ProposalImportResult: ...


class ImportLogServiceProtocol(Protocol):
    def list_log_entries(
        self,
        *,
        event_id: int,
        pk: int,
        status: ImportLogStatus | None = None,
        search: str = "",
    ) -> list[ImportLogEntryDTO]: ...
    def log_entry_for_session(self, session_pk: int) -> ImportLogEntryDTO | None: ...
    def retry_entry(self, *, sphere_id: int, event_id: int, entry_pk: int) -> bool: ...
    def reimport_entry(
        self, *, sphere_id: int, event_id: int, entry_pk: int
    ) -> bool: ...


class ImportFieldLayoutServiceProtocol(Protocol):
    def apply_field_layout(
        self, event_id: int, integration_pk: int
    ) -> ApplyFieldLayoutResult: ...


# --- CFP (personal-data field management) ---


@dataclass
class PersonalDataFieldFormContextDTO:
    """Read aggregate for the personal-data-field create form."""

    categories: list[ProposalCategoryDTO]


@dataclass
class PersonalDataFieldEditContextDTO:
    """Read aggregate for the personal-data-field edit form."""

    field: PersonalDataFieldDTO
    categories: list[ProposalCategoryDTO]
    required_category_pks: set[int]
    optional_category_pks: set[int]


class FacilitatorListFilters(TypedDict, total=False):
    search: str | None
    accreditation: str | None
    flagged: bool | None
    field_filters: dict[int, str | bool] | None
    sort: str | None


class EventPanelSettingsDTO(BaseModel):
    """Organizer-only backoffice settings for an event."""

    model_config = ConfigDict(from_attributes=True)

    facilitator_columns: list[str] = []
    pk: int


class EventPanelSettingsRepositoryProtocol(Protocol):
    @staticmethod
    def read_or_create(event_id: int) -> EventPanelSettingsDTO: ...
    @staticmethod
    def update_facilitator_columns(event_id: int, columns: list[str]) -> None: ...


@dataclass
class FacilitatorPanelRepos:
    """The repos the panel's facilitator list reads and writes through."""

    facilitators: FacilitatorRepositoryProtocol
    personal_data_fields: PersonalDataFieldRepositoryProtocol
    personal_data_field_values: PersonalDataFieldValueRepositoryProtocol
    facilitator_change_logs: FacilitatorChangeLogRepositoryProtocol
    panel_settings: EventPanelSettingsRepositoryProtocol


@dataclass
class FacilitatorListQuery:
    """The list's requested view: filters as the request spelled them.

    `raw_field_filters` is keyed by personal-data field pk with the value
    untouched from the query string; the service resolves it against the
    event's own fields.
    """

    search: str = ""
    accreditation: str = ""
    flagged: bool = False
    sort: str = ""
    raw_field_filters: dict[int, str] = field(default_factory=dict)


@dataclass
class FacilitatorColumnDTO:
    """One column of the panel's facilitator list.

    `key` is both the column's identity and its sort key — a built-in
    ("name", "linked", "sessions", "accreditation") or "field_<pk>". `field`
    is set only for personal-data columns; built-ins label themselves in the
    template, where the rest of the list's wording lives.
    """

    key: str
    field: PersonalDataFieldDTO | None = None


@dataclass
class FacilitatorListContextDTO:
    """Read aggregate for the panel's facilitator list."""

    facilitators: list[FacilitatorListItemDTO]
    filterable_fields: list[PersonalDataFieldDTO]
    field_filters: dict[int, str | bool]
    columns: list[FacilitatorColumnDTO]


@dataclass
class FacilitatorColumnsContextDTO:
    """Read aggregate for the facilitator-columns chooser."""

    chosen: list[FacilitatorColumnDTO]
    available: list[FacilitatorColumnDTO]


class FacilitatorPanelServiceProtocol(Protocol):
    def list_context(
        self, *, event_id: int, query: FacilitatorListQuery
    ) -> FacilitatorListContextDTO: ...
    def column_values(
        self, *, facilitator_ids: list[int], field_ids: list[int]
    ) -> dict[int, dict[str, str | list[str] | bool]]: ...
    def columns_context(self, event_id: int) -> FacilitatorColumnsContextDTO: ...
    def set_columns(self, *, event_id: int, columns: list[str]) -> None: ...
    def set_flag(
        self, *, event_id: int, facilitator_slug: str, flagged: bool
    ) -> None: ...
    def assign_organizer(
        self, *, event_id: int, facilitator_slug: str, organizer_id: int
    ) -> bool: ...
    def unassign_organizer(
        self, *, event_id: int, facilitator_slug: str, organizer_id: int, force: bool
    ) -> bool: ...
    def set_accreditation(
        self,
        *,
        event_id: int,
        facilitator_slug: str,
        accreditation_type: str,
        user_id: int | None = None,
    ) -> None: ...


class CFPPersonalDataFieldServiceProtocol(Protocol):
    def list_summaries(self, event_pk: int) -> list[FieldUsageSummary]: ...
    def get_create_form_context(
        self, event_pk: int
    ) -> PersonalDataFieldFormContextDTO: ...
    def get_edit_form_context(
        self, event_pk: int, field_slug: str
    ) -> PersonalDataFieldEditContextDTO: ...
    def create(
        self,
        *,
        event_pk: int,
        data: PersonalDataFieldCreateData,
        category_requirements: dict[int, bool],
    ) -> PersonalDataFieldDTO: ...
    def update(
        self,
        *,
        event_pk: int,
        field_slug: str,
        data: PersonalDataFieldUpdateData,
        category_requirements: dict[int, bool],
    ) -> None: ...
    def delete(self, event_pk: int, field_slug: str) -> bool: ...


class PersonalDataFieldValueServiceProtocol(Protocol):
    def update_personal_data(
        self,
        *,
        event_id: int,
        facilitator_id: int,
        entries: list[PersonalDataFieldValueData],
        user_id: int | None = None,
    ) -> None: ...
    def update_facilitator(
        self,
        *,
        event_id: int,
        facilitator_id: int,
        data: FacilitatorUpdateData,
        entries: list[PersonalDataFieldValueData],
        user_id: int | None = None,
    ) -> None: ...
    def list_log(self, event_id: int) -> list[FacilitatorChangeLogDTO]: ...
    def list_field_names(self, event_id: int) -> dict[int, str]: ...
