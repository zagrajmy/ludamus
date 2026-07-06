from ludamus.adapters.db.django.models import Discount
from ludamus.pacts import NotFoundError
from ludamus.pacts.discounts import (
    DiscountData,
    DiscountDTO,
    DiscountRepositoryProtocol,
)


class DiscountRepository(DiscountRepositoryProtocol):
    @staticmethod
    def list_by_event(event_pk: int) -> list[DiscountDTO]:
        return [
            DiscountDTO.model_validate(d)
            for d in Discount.objects.filter(event_id=event_pk)
        ]

    @staticmethod
    def get(pk: int) -> DiscountDTO:
        try:
            discount = Discount.objects.get(pk=pk)
        except Discount.DoesNotExist as exception:
            raise NotFoundError from exception
        return DiscountDTO.model_validate(discount)

    @staticmethod
    def create(event_pk: int, data: DiscountData) -> DiscountDTO:
        discount = Discount.objects.create(
            event_id=event_pk,
            facilitator_id=data.facilitator_id,
            kind=data.kind,
            value=data.value,
            note=data.note,
        )
        return DiscountDTO.model_validate(discount)

    @staticmethod
    def update(pk: int, data: DiscountData) -> DiscountDTO:
        try:
            discount = Discount.objects.get(pk=pk)
        except Discount.DoesNotExist as exception:
            raise NotFoundError from exception
        discount.facilitator_id = data.facilitator_id
        discount.kind = data.kind
        discount.value = data.value
        discount.note = data.note
        discount.save(
            update_fields=["facilitator", "kind", "value", "note", "modification_time"]
        )
        return DiscountDTO.model_validate(discount)

    @staticmethod
    def soft_delete(pk: int) -> None:
        # Reach through `all_objects` so an already-dead row raises NotFound
        # instead of silently re-stamping `deleted_at`.
        try:
            discount = Discount.all_objects.get(id=pk, deleted_at__isnull=True)
        except Discount.DoesNotExist as exception:
            raise NotFoundError from exception
        discount.soft_delete()
