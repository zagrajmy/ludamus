"""Shared create/update flow for the CFP field services.

Personal-data fields and session fields differ only in which category link
table they write to, so the transaction and the event-scoping of the submitted
category pks live here once.
"""

from typing import TYPE_CHECKING

from ludamus.pacts.submissions import HasPk

if TYPE_CHECKING:
    from ludamus.pacts import ProposalCategoryRepositoryProtocol
    from ludamus.pacts.services import TransactionProtocol
    from ludamus.pacts.submissions import CFPFieldRepositoryProtocol


class CFPFieldCategoryService[CreateT, UpdateT, DtoT: HasPk]:
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

    def _add_to_categories(self, field_pk: int, scoped: dict[int, bool]) -> None:
        raise NotImplementedError

    def _set_categories(self, field_pk: int, scoped: dict[int, bool]) -> None:
        raise NotImplementedError

    def _scope_to_event(
        self, event_pk: int, category_requirements: dict[int, bool]
    ) -> dict[int, bool]:
        valid_pks = {c.pk for c in self._categories.list_by_event(event_pk)}
        return {pk: req for pk, req in category_requirements.items() if pk in valid_pks}

    def create(
        self, *, event_pk: int, data: CreateT, category_requirements: dict[int, bool]
    ) -> DtoT:
        with self._transaction.atomic():
            field = self._fields.create(event_pk, data)
            if scoped := self._scope_to_event(event_pk, category_requirements):
                self._add_to_categories(field.pk, scoped)
        return field

    def update(
        self,
        *,
        event_pk: int,
        field_slug: str,
        data: UpdateT,
        category_requirements: dict[int, bool],
    ) -> None:
        field = self._fields.read_by_slug(event_pk, field_slug)
        scoped = self._scope_to_event(event_pk, category_requirements)
        with self._transaction.atomic():
            self._fields.update(field.pk, data)
            self._set_categories(field.pk, scoped)
