"""Backoffice management of an event's session fields."""

from typing import TYPE_CHECKING

from ludamus.pacts.submissions import CFPSessionFieldServiceProtocol

if TYPE_CHECKING:
    from ludamus.pacts import (
        OrganizerFieldDTO,
        ProposalCategoryRepositoryProtocol,
        SessionFieldRepositoryProtocol,
    )
    from ludamus.pacts.legacy import SessionFieldCreateData, SessionFieldUpdateData
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.submissions import RequirementSelectionDTO


class CFPSessionFieldService(CFPSessionFieldServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        fields: SessionFieldRepositoryProtocol,
        categories: ProposalCategoryRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._fields = fields
        self._categories = categories

    def create(
        self,
        *,
        event_pk: int,
        data: SessionFieldCreateData,
        category_requirements: RequirementSelectionDTO,
    ) -> OrganizerFieldDTO:
        with self._transaction.atomic():
            field = self._fields.create(event_pk, data)
            if scoped := self._scoped(event_pk, category_requirements):
                self._categories.set_session_field_categories(field.pk, scoped)
        return field

    def update(
        self,
        *,
        event_pk: int,
        field_slug: str,
        data: SessionFieldUpdateData,
        category_requirements: RequirementSelectionDTO,
    ) -> None:
        field = self._fields.read_by_slug(event_pk, field_slug)
        scoped = self._scoped(event_pk, category_requirements)
        with self._transaction.atomic():
            self._fields.update(field.pk, data)
            self._categories.set_session_field_categories(field.pk, scoped)

    def _scoped(
        self, event_pk: int, category_requirements: RequirementSelectionDTO
    ) -> dict[int, bool]:
        return category_requirements.scoped_to(
            self._categories.list_by_event(event_pk)
        ).requirements
