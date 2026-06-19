from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ludamus.pacts.discounts import (
        DiscountData,
        DiscountDTO,
        DiscountRepositoryProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


class DiscountsService:
    def __init__(
        self, transaction: TransactionProtocol, discounts: DiscountRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._discounts = discounts

    def list_by_event(self, event_pk: int) -> list[DiscountDTO]:
        return self._discounts.list_by_event(event_pk)

    def get(self, pk: int) -> DiscountDTO:
        return self._discounts.get(pk)

    def create(self, event_pk: int, data: DiscountData) -> DiscountDTO:
        with self._transaction.atomic():
            return self._discounts.create(event_pk, data)

    def update(self, pk: int, data: DiscountData) -> DiscountDTO:
        with self._transaction.atomic():
            return self._discounts.update(pk, data)

    def soft_delete(self, pk: int) -> None:
        with self._transaction.atomic():
            self._discounts.soft_delete(pk)
