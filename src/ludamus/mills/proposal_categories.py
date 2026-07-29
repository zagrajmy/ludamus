from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.proposal_categories import (
    ProposalCategoriesPageDTO,
    ProposalCategoriesServiceProtocol,
)

if TYPE_CHECKING:
    from ludamus.pacts.legacy import ProposalCategoryDTO
    from ludamus.pacts.proposal_categories import ProposalCategoriesRepositoryProtocol
    from ludamus.pacts.services import TransactionProtocol


class ProposalCategoriesService(ProposalCategoriesServiceProtocol):
    def __init__(
        self,
        transaction: TransactionProtocol,
        categories: ProposalCategoriesRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._categories = categories

    def get_page_context(self, event_pk: int) -> ProposalCategoriesPageDTO:
        return ProposalCategoriesPageDTO(
            categories=self._categories.list_by_event(event_pk),
            stats=self._categories.get_category_stats(event_pk),
        )

    def create(self, event_pk: int, name: str) -> ProposalCategoryDTO:
        with self._transaction.atomic():
            return self._categories.create(event_pk, name)

    def delete_by_slug(self, event_pk: int, category_slug: str) -> bool:
        # read_by_slug is event-scoped, so a foreign slug raises NotFoundError
        # before anything is touched.
        category = self._categories.read_by_slug(event_pk, category_slug)
        with self._transaction.atomic():
            if self._categories.has_proposals(category.pk):
                return False
            self._categories.delete(category.pk)
        return True
