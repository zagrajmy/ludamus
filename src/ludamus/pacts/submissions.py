"""Submissions subdomain DTOs and protocols.

Owns proposal intake: the CFP configuration (personal-data fields) bounded
context today, with the Session lifecycle and proposal import to follow.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ludamus.pacts.legacy import (
        FieldUsageSummary,
        PersonalDataFieldCreateData,
        PersonalDataFieldDTO,
        PersonalDataFieldRepositoryProtocol,
        PersonalDataFieldUpdateData,
        ProposalCategoryDTO,
        SessionFieldRepositoryProtocol,
    )


# --- Proposal import (mapping recipe stored as the integration's settings) ---


class QuestionTarget(BaseModel):
    # `to` is "session.<col>" (a built-in proposal field), "field.<Name>" (a new
    # session field) or "personal.<Name>" (a new personal-data field), each
    # provisioned by name from `ImportSettings.definitions`; `ignore` marks a
    # question as deliberately unmapped.
    to: str | None = None
    ignore: bool = False


class FieldDefinition(BaseModel):
    # Setup for a brand-new target field, keyed by its name under
    # `FieldDefinitions`. Multi-choice is `select` + `multiple` (the domain has
    # no multi `checkbox`); `options` is the explicit, operator-editable list.
    type: Literal["text", "select", "checkbox"] = "text"
    multiple: bool = False
    allow_custom: bool = False
    options: list[str] = []


class FieldDefinitions(BaseModel):
    personal_fields: dict[str, FieldDefinition] = {}
    session_fields: dict[str, FieldDefinition] = {}


class ImportSettings(BaseModel):
    questions: dict[str, QuestionTarget] = {}
    definitions: FieldDefinitions = Field(default_factory=FieldDefinitions)


class ProposalSourceProtocol(Protocol):
    # Raw rows from the integration's source: one dict per response,
    # keyed by source question (header). Decrypt + dispatch lives in
    # Chronology; Submissions only interprets the strings.
    def fetch_responses(
        self, sphere_id: int, event_id: int, pk: int
    ) -> list[dict[str, str]]: ...


@dataclass
class ProposalImportResult:
    created: int
    fields_created: int


@dataclass(frozen=True)
class FieldRepos:
    """The field repos the proposal importer provisions new fields into."""

    session: SessionFieldRepositoryProtocol
    personal: PersonalDataFieldRepositoryProtocol


class ProposalImportServiceProtocol(Protocol):
    def run(
        self, sphere_id: int, event_id: int, integration_pk: int
    ) -> ProposalImportResult: ...
    def run_sample(
        self, sphere_id: int, event_id: int, integration_pk: int
    ) -> ProposalImportResult: ...


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
