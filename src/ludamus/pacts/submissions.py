"""Submissions subdomain DTOs and protocols.

Owns proposal intake: the CFP configuration (personal-data fields) bounded
context today, with the Session lifecycle and proposal import to follow.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ludamus.pacts.legacy import (
        FieldUsageSummary,
        PersonalDataFieldCreateData,
        PersonalDataFieldDTO,
        PersonalDataFieldUpdateData,
        ProposalCategoryDTO,
    )

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
