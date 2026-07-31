from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ludamus.mills.discounts import DiscountsService
from ludamus.pacts import FacilitatorDTO, NotFoundError
from ludamus.pacts.discounts import (
    DiscountData,
    DiscountDTO,
    DiscountKind,
    DiscountRosterEntryDTO,
)
from ludamus.pacts.legacy import FacilitatorListItemDTO


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    def __init__(self):
        self.entered = 0

    def atomic(self):
        self.entered += 1
        return _atomic()


def _dto(pk, *, event_id=1, facilitator_id=1):
    return DiscountDTO(
        pk=pk,
        event_id=event_id,
        facilitator_id=facilitator_id,
        kind=DiscountKind.PERCENT,
        value=Decimal("10.00"),
        note=f"note-{pk}",
        creation_time=datetime(2026, 6, 19, tzinfo=UTC),
        modification_time=datetime(2026, 6, 19, tzinfo=UTC),
    )


def _facilitator(pk=1, event_id=1):
    return FacilitatorDTO(
        accreditation_type="standard",
        display_name="Ada",
        event_id=event_id,
        pk=pk,
        slug="ada",
        user_id=None,
    )


def _list_item(pk=1):
    return FacilitatorListItemDTO(
        accreditation_type="standard",
        display_name="Ada",
        pk=pk,
        session_count=0,
        slug="ada",
        user_id=None,
    )


class FakeRepo:
    def __init__(self, *, items=()):
        self._items = list(items)
        self.created = []
        self.updated = []
        self.soft_deleted = []

    def list_by_event(self, event_pk):
        return [d for d in self._items if d.event_id == event_pk]

    def get(self, pk):
        for discount in self._items:
            if discount.pk == pk:
                return discount
        raise NotFoundError

    def create(self, event_pk, data):
        self.created.append((event_pk, data))
        return _dto(99, event_id=event_pk, facilitator_id=data.facilitator_id)

    def update(self, pk, data):
        self.updated.append((pk, data))
        return _dto(pk, facilitator_id=data.facilitator_id)

    def soft_delete(self, pk):
        self.soft_deleted.append(pk)


class FakeFacilitators:
    def __init__(self, *, list_items=(), facilitators=()):
        self._list_items = list(list_items)
        self._facilitators = {f.pk: f for f in facilitators}

    def list_by_event(self, _event_id):
        return list(self._list_items)

    def read(self, pk):
        try:
            return self._facilitators[pk]
        except KeyError:
            raise NotFoundError from None


def _service(*, repo=None, facilitators=None, transaction=None):
    return DiscountsService(
        transaction=transaction or FakeTransaction(),
        discounts=repo or FakeRepo(),
        facilitators=facilitators or FakeFacilitators(),
    )


def _data(facilitator_id=1):
    return DiscountData(
        facilitator_id=facilitator_id,
        kind=DiscountKind.PERCENT,
        value=Decimal("10.00"),
        note="note",
    )


class TestDiscountsService:
    def test_list_roster_pairs_facilitators_with_their_discounts(self):
        discount = _dto(1, facilitator_id=1)
        repo = FakeRepo(items=[discount, _dto(2, event_id=2, facilitator_id=2)])
        facilitators = FakeFacilitators(list_items=[_list_item(pk=1), _list_item(pk=2)])
        service = _service(repo=repo, facilitators=facilitators)

        result = service.list_roster(1)

        assert result == [
            DiscountRosterEntryDTO(facilitator=_list_item(pk=1), discount=discount),
            DiscountRosterEntryDTO(facilitator=_list_item(pk=2), discount=None),
        ]

    def test_read_scoped_returns_discount_from_current_event(self):
        pk = 7
        repo = FakeRepo(items=[_dto(pk, event_id=1)])
        service = _service(repo=repo)

        result = service.read_scoped(event_pk=1, pk=pk)

        assert result == _dto(pk, event_id=1)

    def test_read_scoped_rejects_foreign_event_discount(self):
        pk = 7
        repo = FakeRepo(items=[_dto(pk, event_id=2)])
        service = _service(repo=repo)

        with pytest.raises(NotFoundError):
            service.read_scoped(event_pk=1, pk=pk)

        assert not repo.updated
        assert not repo.soft_deleted

    def test_read_scoped_propagates_not_found(self):
        service = _service(repo=FakeRepo())

        with pytest.raises(NotFoundError):
            service.read_scoped(event_pk=1, pk=999)

    def test_read_scoped_facilitator_returns_facilitator_from_current_event(self):
        facilitator = _facilitator(pk=3, event_id=1)
        service = _service(facilitators=FakeFacilitators(facilitators=[facilitator]))

        result = service.read_scoped_facilitator(event_pk=1, facilitator_id=3)

        assert result == facilitator

    def test_read_scoped_facilitator_rejects_foreign_event_facilitator(self):
        facilitators = FakeFacilitators(facilitators=[_facilitator(pk=3, event_id=2)])
        service = _service(facilitators=facilitators)

        with pytest.raises(NotFoundError):
            service.read_scoped_facilitator(event_pk=1, facilitator_id=3)

    def test_read_scoped_facilitator_propagates_not_found(self):
        service = _service(facilitators=FakeFacilitators())

        with pytest.raises(NotFoundError):
            service.read_scoped_facilitator(event_pk=1, facilitator_id=999)

    def test_create_runs_in_transaction(self):
        created_pk = 99
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = _service(repo=repo, transaction=transaction)
        data = _data()

        result = service.create(1, data)

        assert transaction.entered == 1
        assert repo.created == [(1, data)]
        assert result == _dto(created_pk)

    def test_update_runs_in_transaction(self):
        pk = 5
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = _service(repo=repo, transaction=transaction)
        data = _data()

        result = service.update(pk, data)

        assert transaction.entered == 1
        assert repo.updated == [(pk, data)]
        assert result == _dto(pk)

    def test_soft_delete_runs_in_transaction(self):
        pk = 5
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = _service(repo=repo, transaction=transaction)

        service.soft_delete(pk)

        assert transaction.entered == 1
        assert repo.soft_deleted == [pk]
