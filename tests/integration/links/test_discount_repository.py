from decimal import Decimal

import pytest
from django.db import IntegrityError

from ludamus.adapters.db.django.models import Discount, Facilitator
from ludamus.links.db.django.repositories import DiscountRepository
from ludamus.pacts import NotFoundError
from ludamus.pacts.discounts import DiscountData, DiscountDTO, DiscountKind


@pytest.fixture(name="facilitator")
def facilitator_fixture(event):
    return Facilitator.objects.create(
        event=event, display_name="Creator", slug="creator"
    )


@pytest.fixture(name="other_facilitator")
def other_facilitator_fixture(event):
    return Facilitator.objects.create(event=event, display_name="Other", slug="other")


class TestDiscountRepositoryList:
    def test_list_by_event_returns_dtos(self, event, facilitator):
        discount = Discount.objects.create(
            event=event,
            facilitator=facilitator,
            kind=DiscountKind.PERCENT,
            value=Decimal("10.00"),
        )

        result = DiscountRepository.list_by_event(event.pk)

        assert result == [DiscountDTO.model_validate(discount)]

    def test_list_by_event_excludes_soft_deleted(self, event, facilitator):
        discount = Discount.objects.create(
            event=event,
            facilitator=facilitator,
            kind=DiscountKind.AMOUNT,
            value=Decimal("5.00"),
        )
        discount.soft_delete()

        result = DiscountRepository.list_by_event(event.pk)

        assert result == []


class TestDiscountRepositoryGet:
    def test_get_returns_dto(self, event, facilitator):
        discount = Discount.objects.create(
            event=event,
            facilitator=facilitator,
            kind=DiscountKind.PERCENT,
            value=Decimal("15.50"),
            note="welcome",
        )

        result = DiscountRepository.get(discount.pk)

        assert result == DiscountDTO.model_validate(discount)

    def test_get_raises_for_missing(self):
        missing_pk = 9999

        with pytest.raises(NotFoundError):
            DiscountRepository.get(missing_pk)

    def test_get_raises_for_soft_deleted(self, event, facilitator):
        discount = Discount.objects.create(
            event=event,
            facilitator=facilitator,
            kind=DiscountKind.AMOUNT,
            value=Decimal("20.00"),
        )
        discount.soft_delete()

        with pytest.raises(NotFoundError):
            DiscountRepository.get(discount.pk)


class TestDiscountRepositoryWrite:
    def test_create_persists_fields(self, event, facilitator):
        data = DiscountData(
            facilitator_id=facilitator.pk,
            kind=DiscountKind.PERCENT,
            value=Decimal("25.00"),
            note="creator perk",
        )

        result = DiscountRepository.create(event.pk, data)

        stored = Discount.objects.get(pk=result.pk)
        assert stored.event_id == event.pk
        assert stored.facilitator_id == facilitator.pk
        assert stored.kind == DiscountKind.PERCENT
        assert stored.value == Decimal("25.00")
        assert stored.note == "creator perk"

    def test_update_changes_fields(self, event, facilitator, other_facilitator):
        discount = Discount.objects.create(
            event=event,
            facilitator=facilitator,
            kind=DiscountKind.PERCENT,
            value=Decimal("10.00"),
            note="old",
        )
        data = DiscountData(
            facilitator_id=other_facilitator.pk,
            kind=DiscountKind.AMOUNT,
            value=Decimal("30.00"),
            note="new",
        )

        DiscountRepository.update(discount.pk, data)

        discount.refresh_from_db()
        assert discount.facilitator_id == other_facilitator.pk
        assert discount.kind == DiscountKind.AMOUNT
        assert discount.value == Decimal("30.00")
        assert discount.note == "new"

    def test_update_raises_for_missing(self, facilitator):
        missing_pk = 9999
        data = DiscountData(
            facilitator_id=facilitator.pk,
            kind=DiscountKind.AMOUNT,
            value=Decimal("1.00"),
        )

        with pytest.raises(NotFoundError):
            DiscountRepository.update(missing_pk, data)


class TestDiscountRepositorySoftDelete:
    def test_soft_delete_hides_row(self, event, facilitator):
        discount = Discount.objects.create(
            event=event,
            facilitator=facilitator,
            kind=DiscountKind.PERCENT,
            value=Decimal("10.00"),
        )

        DiscountRepository.soft_delete(discount.pk)

        assert not Discount.objects.filter(pk=discount.pk).exists()
        assert Discount.all_objects.filter(pk=discount.pk).exists()

    def test_soft_delete_is_reversible(self, event, facilitator):
        discount = Discount.objects.create(
            event=event,
            facilitator=facilitator,
            kind=DiscountKind.PERCENT,
            value=Decimal("10.00"),
        )
        DiscountRepository.soft_delete(discount.pk)

        Discount.all_objects.get(pk=discount.pk).restore()

        assert Discount.objects.filter(pk=discount.pk).exists()

    def test_soft_delete_raises_for_missing(self):
        missing_pk = 9999

        with pytest.raises(NotFoundError):
            DiscountRepository.soft_delete(missing_pk)

    def test_soft_delete_raises_when_already_dead(self, event, facilitator):
        discount = Discount.objects.create(
            event=event,
            facilitator=facilitator,
            kind=DiscountKind.PERCENT,
            value=Decimal("10.00"),
        )
        discount.soft_delete()

        with pytest.raises(NotFoundError):
            DiscountRepository.soft_delete(discount.pk)


class TestDiscountRepositoryUniqueConstraint:
    def test_alive_duplicate_is_rejected(self, event, facilitator):
        data = DiscountData(
            facilitator_id=facilitator.pk,
            kind=DiscountKind.PERCENT,
            value=Decimal("10.00"),
        )
        DiscountRepository.create(event.pk, data)

        with pytest.raises(IntegrityError):
            DiscountRepository.create(event.pk, data)

    def test_can_recreate_after_soft_delete(self, event, facilitator):
        data = DiscountData(
            facilitator_id=facilitator.pk,
            kind=DiscountKind.PERCENT,
            value=Decimal("10.00"),
        )
        first = DiscountRepository.create(event.pk, data)
        DiscountRepository.soft_delete(first.pk)

        second = DiscountRepository.create(event.pk, data)

        assert second.pk != first.pk
        assert DiscountRepository.list_by_event(event.pk) == [
            DiscountDTO.model_validate(Discount.objects.get(pk=second.pk))
        ]
