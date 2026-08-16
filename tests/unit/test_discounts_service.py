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
    DiscountMethod,
    DiscountRosterEntryDTO,
    DiscountRuleDTO,
    DiscountSyncResultDTO,
    FacilitatorScheduleRow,
)
from ludamus.pacts.event import FacilitatorListItemDTO


@contextmanager
def _atomic():
    yield


class FakeTransaction:
    def __init__(self):
        self.entered = 0

    def atomic(self):
        self.entered += 1
        return _atomic()


def _dto(pk, *, event_id=1, facilitator_id=1, from_rules=False):
    return DiscountDTO(
        pk=pk,
        event_id=event_id,
        facilitator_id=facilitator_id,
        kind=DiscountKind.PERCENT,
        value=Decimal("10.00"),
        note=f"note-{pk}",
        from_rules=from_rules,
        creation_time=datetime(2026, 6, 19, tzinfo=UTC),
        modification_time=datetime(2026, 6, 19, tzinfo=UTC),
    )


def _rule(pk, *, method=DiscountMethod.STARTED_HOURS, quantity=1, percent=50, order=0):
    return DiscountRuleDTO(
        pk=pk,
        event_id=1,
        method=method,
        quantity=quantity,
        percent=Decimal(percent),
        order=order,
    )


def _load(facilitator_id=1, *, session_count=1, minutes=60):
    return FacilitatorScheduleRow(
        facilitator_id=facilitator_id, session_count=session_count, minutes=minutes
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


def _list_item(pk=1, accreditation_type="standard"):
    return FacilitatorListItemDTO(
        accreditation_type=accreditation_type,
        display_name="Ada",
        pk=pk,
        session_count=0,
        slug=f"ada-{pk}",
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
        self.accreditations = []

    def list_by_event(self, _event_id):
        return list(self._list_items)

    def read(self, pk):
        try:
            return self._facilitators[pk]
        except KeyError:
            raise NotFoundError from None

    def set_accreditation(self, *, event_id, pks, accreditation_type):
        self.accreditations.append((event_id, sorted(pks), accreditation_type))


class FakeRules:
    def __init__(self, *, rules=()):
        self._rules = list(rules)

    def list_for_event(self, event_id):
        return [rule for rule in self._rules if rule.event_id == event_id]


class FakeSchedule:
    def __init__(self, *, rows=()):
        self._rows = list(rows)

    def list_facilitator_schedule(self, _event_pk):
        return list(self._rows)


class FakeChangeLogs:
    def __init__(self):
        self.batches = []

    def create_many(self, data):
        self.batches.append(list(data))


def _service(
    *,
    repo=None,
    facilitators=None,
    transaction=None,
    rules=None,
    schedule=None,
    change_logs=None,
):
    return DiscountsService(
        transaction=transaction or FakeTransaction(),
        discounts=repo or FakeRepo(),
        facilitators=facilitators or FakeFacilitators(),
        rules=rules or FakeRules(),
        schedule=schedule or FakeSchedule(),
        facilitator_change_logs=change_logs or FakeChangeLogs(),
    )


def _data(facilitator_id=1):
    return DiscountData(
        facilitator_id=facilitator_id,
        kind=DiscountKind.PERCENT,
        value=Decimal("10.00"),
        note="note",
        from_rules=False,
    )


def _log(facilitator_id, old, new, *, event_id=1, user_id=7):
    return {
        "event_id": event_id,
        "facilitator_id": facilitator_id,
        "user_id": user_id,
        "changes": [
            {"field": "accreditation_type", "field_id": None, "old": old, "new": new}
        ],
    }


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


class TestApplyFromAgenda:
    @staticmethod
    def _apply(*, list_items, rows, rules=(), discounts=()):
        repo = FakeRepo(items=discounts)
        facilitators = FakeFacilitators(list_items=list_items)
        change_logs = FakeChangeLogs()
        service = _service(
            repo=repo,
            facilitators=facilitators,
            rules=FakeRules(rules=rules),
            schedule=FakeSchedule(rows=rows),
            change_logs=change_logs,
        )
        result = service.apply_from_agenda(event_pk=1, user_id=7)
        return result, repo, facilitators, change_logs

    def test_scheduled_facilitator_becomes_creator_with_the_matching_discount(self):
        percent = Decimal(50)
        result, repo, facilitators, change_logs = self._apply(
            list_items=[_list_item(pk=1, accreditation_type="none")],
            rows=[_load(1, minutes=60)],
            rules=[_rule(1, quantity=1, percent=percent)],
        )

        assert facilitators.accreditations == [(1, [1], "creator")]
        assert change_logs.batches == [[_log(1, "none", "creator")]]
        assert repo.created == [
            (
                1,
                DiscountData(
                    facilitator_id=1,
                    kind=DiscountKind.PERCENT,
                    value=percent,
                    from_rules=True,
                ),
            )
        ]
        assert result.marked == 1
        assert result.discounts_set == 1

    def test_started_hours_round_the_total_up(self):
        # Two 25-minute points are 50 minutes — one started hour, not two.
        result, repo, _facilitators, _change_logs = self._apply(
            list_items=[_list_item(pk=1, accreditation_type="none")],
            rows=[_load(1, session_count=2, minutes=50)],
            rules=[_rule(1, quantity=2, order=0), _rule(2, quantity=1, order=1)],
        )

        assert [data.value for _event_pk, data in repo.created] == [Decimal(50)]
        assert result.discounts_set == 1

    def test_first_rule_in_order_wins(self):
        low, high = Decimal(25), Decimal(75)
        _result, repo, _facilitators, _change_logs = self._apply(
            list_items=[_list_item(pk=1, accreditation_type="none")],
            rows=[_load(1, minutes=240)],
            rules=[
                _rule(1, quantity=4, percent=high, order=0),
                _rule(2, quantity=1, percent=low, order=1),
            ],
        )

        assert [data.value for _event_pk, data in repo.created] == [high]

    def test_session_count_rule_measures_scheduled_points(self):
        _result, repo, _facilitators, _change_logs = self._apply(
            list_items=[_list_item(pk=1, accreditation_type="none")],
            rows=[_load(1, session_count=3, minutes=30)],
            rules=[
                _rule(1, method=DiscountMethod.SESSION_COUNT, quantity=3, percent=40)
            ],
        )

        assert [data.value for _event_pk, data in repo.created] == [Decimal(40)]

    def test_other_accreditation_types_keep_theirs_and_get_no_discount(self):
        result, repo, facilitators, change_logs = self._apply(
            list_items=[
                _list_item(pk=1, accreditation_type="guest"),
                _list_item(pk=2, accreditation_type="honorary"),
                _list_item(pk=3, accreditation_type="standard"),
            ],
            rows=[_load(1), _load(2), _load(3)],
            rules=[_rule(1)],
        )

        assert not facilitators.accreditations
        assert not change_logs.batches
        assert not repo.created
        assert result == DiscountSyncResultDTO(
            marked=0, unmarked=0, discounts_set=0, discounts_cleared=0
        )

    def test_creator_without_scheduled_program_loses_mark_and_rule_discount(self):
        pk = 4
        result, repo, facilitators, change_logs = self._apply(
            list_items=[_list_item(pk=1, accreditation_type="creator")],
            rows=[],
            rules=[_rule(1)],
            discounts=[_dto(pk, facilitator_id=1, from_rules=True)],
        )

        assert facilitators.accreditations == [(1, [1], "none")]
        assert change_logs.batches == [[_log(1, "creator", "none")]]
        assert repo.soft_deleted == [pk]
        assert result.unmarked == 1
        assert result.discounts_cleared == 1

    def test_hand_assigned_discount_survives_the_sync(self):
        _result, repo, _facilitators, _change_logs = self._apply(
            list_items=[_list_item(pk=1, accreditation_type="none")],
            rows=[_load(1)],
            rules=[_rule(1)],
            discounts=[_dto(4, facilitator_id=1, from_rules=False)],
        )

        assert not repo.created
        assert not repo.updated
        assert not repo.soft_deleted

    def test_every_accreditation_move_is_written_once_per_target(self):
        result, _repo, facilitators, change_logs = self._apply(
            list_items=[
                _list_item(pk=1, accreditation_type="none"),
                _list_item(pk=2, accreditation_type="none"),
                _list_item(pk=3, accreditation_type="creator"),
                _list_item(pk=4, accreditation_type="creator"),
            ],
            rows=[_load(1), _load(2)],
        )

        assert facilitators.accreditations == [
            (1, [1, 2], "creator"),
            (1, [3, 4], "none"),
        ]
        assert change_logs.batches == [
            [
                _log(1, "none", "creator"),
                _log(2, "none", "creator"),
                _log(3, "creator", "none"),
                _log(4, "creator", "none"),
            ]
        ]
        assert result == DiscountSyncResultDTO(
            marked=2, unmarked=2, discounts_set=0, discounts_cleared=0
        )

    def test_creator_without_a_matching_rule_loses_the_rule_discount(self):
        pk = 4
        result, repo, _facilitators, _change_logs = self._apply(
            list_items=[_list_item(pk=1, accreditation_type="creator")],
            rows=[_load(1, minutes=60)],
            rules=[_rule(1, quantity=5)],
            discounts=[_dto(pk, facilitator_id=1, from_rules=True)],
        )

        assert repo.soft_deleted == [pk]
        assert result.discounts_cleared == 1
