"""Submissions subdomain DTOs and protocols.

Owns proposal intake: the CFP configuration (personal-data fields) bounded
context today, with the Session lifecycle and proposal import to follow.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ludamus.pacts.legacy import (
        FacilitatorRepositoryProtocol,
        FieldUsageSummary,
        PersonalDataFieldCreateData,
        PersonalDataFieldDTO,
        PersonalDataFieldRepositoryProtocol,
        PersonalDataFieldUpdateData,
        ProposalCategoryDTO,
        ProposalCategoryRepositoryProtocol,
        SessionFieldRepositoryProtocol,
        SessionRepositoryProtocol,
        TimeSlotRepositoryProtocol,
        TrackRepositoryProtocol,
    )


# --- Proposal import (mapping recipe stored as the integration's settings) ---


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
    # entity it resolves to. `catchall` is the track/category that catches a
    # custom or unmatched answer. `confirmed` is the operator's per-row
    # sign-off in the summary editor; the run gate refuses to import while any
    # mapped question is still unconfirmed.
    to: str | None = None
    ignore: bool = False
    values: dict[str, QuestionValue] = {}
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
    questions: dict[str, QuestionTarget] = {}
    definitions: FieldDefinitions = Field(default_factory=FieldDefinitions)
    header_row: int = 1
    unique_key_columns: list[str] = []


class ImportFailure(BaseModel):
    # A row the importer deliberately skipped (mapping failure). The row index
    # is the response sheet's row position at run time, used as a stable enough
    # key for the Errors tab and the Retry action. `response` is a UI-only
    # snapshot so the operator can see what answer it was without a refetch.
    row_index: int
    reason: str
    response: dict[str, str] = {}


@dataclass
class ProposalImportResult:
    created: int
    fields_created: int
    skipped: int = 0
    duplicates: int = 0


@dataclass(frozen=True)
class ImportRepos:
    """The repos the proposal importer creates proposals and provisions into."""

    sessions: SessionRepositoryProtocol
    session_fields: SessionFieldRepositoryProtocol
    personal_fields: PersonalDataFieldRepositoryProtocol
    time_slots: TimeSlotRepositoryProtocol
    tracks: TrackRepositoryProtocol
    categories: ProposalCategoryRepositoryProtocol
    facilitators: FacilitatorRepositoryProtocol


class ProposalImportServiceProtocol(Protocol):
    def run(
        self, sphere_id: int, event_id: int, integration_pk: int
    ) -> ProposalImportResult: ...
    def run_sample(
        self, sphere_id: int, event_id: int, integration_pk: int
    ) -> ProposalImportResult: ...
    def list_failures(self, event_id: int, pk: int) -> list[ImportFailure]: ...
    def retry_failure(
        self, sphere_id: int, event_id: int, pk: int, row_index: int
    ) -> bool: ...


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
        event_pk: int,
        data: PersonalDataFieldCreateData,
        category_requirements: dict[int, bool],
    ) -> PersonalDataFieldDTO: ...
    def update(
        self,
        event_pk: int,
        field_slug: str,
        data: PersonalDataFieldUpdateData,
        category_requirements: dict[int, bool],
    ) -> None: ...
    def delete(self, event_pk: int, field_slug: str) -> bool: ...
