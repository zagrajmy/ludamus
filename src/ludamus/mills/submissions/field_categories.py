"""Shared create/update flow for the CFP field services.

Personal-data fields and session fields differ only in which category link
table they write to, so the transaction and the event-scoping of the submitted
category pks live here once.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ludamus.pacts.submissions import HasPk, RequirementSelectionDTO

if TYPE_CHECKING:
    from ludamus.pacts import ProposalCategoryRepositoryProtocol
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.submissions import CFPFieldRepositoryProtocol


class CFPFieldCategoryService[CreateT, UpdateT, DtoT: HasPk](ABC):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        fields: CFPFieldRepositoryProtocol[CreateT, UpdateT, DtoT],
        categories: ProposalCategoryRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._fields = fields
        self._categories = categories

    @abstractmethod
    def _set_categories(self, field_pk: int, scoped: dict[int, bool]) -> None: ...

    def create(
        self,
        *,
        event_pk: int,
        data: CreateT,
        category_requirements: RequirementSelectionDTO,
    ) -> DtoT:
        with self._transaction.atomic():
            field = self._fields.create(event_pk, data)
            if scoped := self._scoped(event_pk, category_requirements):
                self._set_categories(field.pk, scoped)
        return field

    def update(
        self,
        *,
        event_pk: int,
        field_slug: str,
        data: UpdateT,
        category_requirements: RequirementSelectionDTO,
    ) -> None:
        field = self._fields.read_by_slug(event_pk, field_slug)
        scoped = self._scoped(event_pk, category_requirements)
        with self._transaction.atomic():
            self._fields.update(field.pk, data)
            self._set_categories(field.pk, scoped)

    def _scoped(
        self, event_pk: int, category_requirements: RequirementSelectionDTO
    ) -> dict[int, bool]:
        return category_requirements.scoped_to(
            self._categories.list_by_event(event_pk)
        ).requirements
