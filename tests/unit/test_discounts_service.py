from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal

from ludamus.mills.discounts import DiscountsService
from ludamus.pacts.discounts import DiscountData, DiscountDTO, DiscountKind


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


class FakeRepo:
    def __init__(self, *, items=()):
        self._items = list(items)
        self.created = []
        self.updated = []
        self.soft_deleted = []

    def list_by_event(self, event_pk):
        return [d for d in self._items if d.event_id == event_pk]

    def get(self, pk):
        return next(d for d in self._items if d.pk == pk)

    def create(self, event_pk, data):
        self.created.append((event_pk, data))
        return _dto(99, event_id=event_pk, facilitator_id=data.facilitator_id)

    def update(self, pk, data):
        self.updated.append((pk, data))
        return _dto(pk, facilitator_id=data.facilitator_id)

    def soft_delete(self, pk):
        self.soft_deleted.append(pk)


def _data(facilitator_id=1):
    return DiscountData(
        facilitator_id=facilitator_id,
        kind=DiscountKind.PERCENT,
        value=Decimal("10.00"),
        note="note",
    )


class TestDiscountsService:
    def test_list_by_event_delegates(self):
        repo = FakeRepo(items=[_dto(1), _dto(2, event_id=2)])
        service = DiscountsService(FakeTransaction(), repo)

        result = service.list_by_event(1)

        assert result == [_dto(1)]

    def test_get_delegates(self):
        pk = 7
        repo = FakeRepo(items=[_dto(pk)])
        service = DiscountsService(FakeTransaction(), repo)

        result = service.get(pk)

        assert result == _dto(pk)

    def test_create_runs_in_transaction(self):
        created_pk = 99
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = DiscountsService(transaction, repo)
        data = _data()

        result = service.create(1, data)

        assert transaction.entered == 1
        assert repo.created == [(1, data)]
        assert result == _dto(created_pk)

    def test_update_runs_in_transaction(self):
        pk = 5
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = DiscountsService(transaction, repo)
        data = _data()

        result = service.update(pk, data)

        assert transaction.entered == 1
        assert repo.updated == [(pk, data)]
        assert result == _dto(pk)

    def test_soft_delete_runs_in_transaction(self):
        pk = 5
        repo = FakeRepo()
        transaction = FakeTransaction()
        service = DiscountsService(transaction, repo)

        service.soft_delete(pk)

        assert transaction.entered == 1
        assert repo.soft_deleted == [pk]
