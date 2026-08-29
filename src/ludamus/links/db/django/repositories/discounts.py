from ludamus.links.db.django.models import Discount, DiscountRule
from ludamus.pacts import NotFoundError
from ludamus.pacts.discounts import (
    DiscountData,
    DiscountDTO,
    DiscountRepositoryProtocol,
    DiscountRuleData,
    DiscountRuleDTO,
    DiscountRuleRepositoryProtocol,
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
            from_rules=data.from_rules,
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
        discount.from_rules = data.from_rules
        discount.save(
            update_fields=[
                "facilitator",
                "kind",
                "value",
                "note",
                "from_rules",
                "modification_time",
            ]
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


class DiscountRuleRepository(DiscountRuleRepositoryProtocol):
    @staticmethod
    def list_for_event(event_id: int) -> list[DiscountRuleDTO]:
        return [
            DiscountRuleDTO.model_validate(rule)
            for rule in DiscountRule.objects.filter(event_id=event_id)
        ]

    @staticmethod
    def read(event_id: int, pk: int) -> DiscountRuleDTO | None:
        rule = DiscountRule.objects.filter(event_id=event_id, pk=pk).first()
        return DiscountRuleDTO.model_validate(rule) if rule else None

    @staticmethod
    def create(event_id: int, data: DiscountRuleData) -> DiscountRuleDTO:
        rule = DiscountRule.objects.create(event_id=event_id, **data.model_dump())
        return DiscountRuleDTO.model_validate(rule)

    @staticmethod
    def update(
        *, event_id: int, pk: int, data: DiscountRuleData
    ) -> DiscountRuleDTO | None:
        updated = DiscountRule.objects.filter(event_id=event_id, pk=pk).update(
            **data.model_dump()
        )
        if not updated:
            return None
        return DiscountRuleDTO.model_validate(
            DiscountRule.objects.get(event_id=event_id, pk=pk)
        )

    @staticmethod
    def delete(event_id: int, pk: int) -> bool:
        deleted, _details = DiscountRule.objects.filter(
            event_id=event_id, pk=pk
        ).delete()
        return deleted > 0
