from datetime import UTC, datetime
from decimal import Decimal

import pytest

from ludamus.mills.discounts import DiscountsService
from ludamus.pacts.discounts import (
    DiscountData,
    DiscountDTO,
    DiscountKind,
    DiscountMethod,
    DiscountRuleData,
    DiscountRuleDTO,
    DiscountSyncResultDTO,
    FacilitatorScheduleRow,
)
from ludamus.pacts.event import FacilitatorListItemDTO
from ludamus.pacts.legacy import FacilitatorDTO, NotFoundError
from tests.unit.factories import FakeTransaction

EVENT_PK = 1


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
        return next(d for d in self._items if d.pk == pk)

    def create(self, event_pk, data):
        self.created.append((event_pk, data))
        return _dto(99, event_id=event_pk, facilitator_id=data.facilitator_id)

    def update(self, pk, data):
        self.updated.append((pk, data))
        return _dto(pk, facilitator_id=data.facilitator_id)

    def soft_delete(self, pk):
        self.soft_deleted.append(pk)


class FakeFacilitators:
    def __init__(self, *, list_items=(), facilitator=None):
        self._by_event = {EVENT_PK: list(list_items)}
        self._facilitators = {facilitator.pk: facilitator} if facilitator else {}
        self.accreditations = []

    def list_by_event(self, event_id):
        return list(self._by_event.get(event_id, []))

    def read(self, pk):
        return self._facilitators[pk]

    def set_accreditation(self, *, event_id, pks, accreditation_type):
        self.accreditations.append((event_id, sorted(pks), accreditation_type))


class FakeRules:
    def __init__(self, *, rules=()):
        self._rules = {rule.pk: rule for rule in rules}

    def list_for_event(self, event_id):
        return [rule for rule in self._rules.values() if rule.event_id == event_id]

    def read(self, event_id, pk):
        rule = self._rules.get(pk)
        return rule if rule and rule.event_id == event_id else None

    def create(self, event_id, data):
        rule = DiscountRuleDTO(pk=len(self._rules) + 1, event_id=event_id, **dict(data))
        self._rules[rule.pk] = rule
        return rule

    def update(self, *, event_id, pk, data):
        if self.read(event_id, pk) is None:
            return None
        self._rules[pk] = DiscountRuleDTO(pk=pk, event_id=event_id, **dict(data))
        return self._rules[pk]

    def delete(self, event_id, pk):
        if self.read(event_id, pk) is None:
            return False
        del self._rules[pk]
        return True


class FakeSchedule:
    def __init__(self, *, rows=()):
        self._by_event = {EVENT_PK: list(rows)}

    def list_facilitator_schedule(self, event_pk):
        return list(self._by_event.get(event_pk, []))


class FakeChangeLogs:
    def __init__(self):
        self.batches = []

    def create_many(self, data):
        self.batches.append(list(data))


def _service(
    *, repo=None, facilitators=None, rules=None, schedule=None, change_logs=None
):
    return DiscountsService(
        transaction=FakeTransaction(),
        discounts=repo or FakeRepo(),
        facilitators=facilitators or FakeFacilitators(),
        rules=rules or FakeRules(),
        schedule=schedule or FakeSchedule(),
        facilitator_change_logs=change_logs or FakeChangeLogs(),
    )


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
        result = service.apply_from_agenda(event_pk=EVENT_PK, user_id=7)
        return result, repo, facilitators, change_logs

    def test_started_hours_round_the_total_up(self):
        # Two 25-minute points are 50 minutes — one started hour, not two.
        result, repo, _facilitators, _change_logs = self._apply(
            list_items=[_list_item(pk=1, accreditation_type="none")],
            rows=[_load(1, session_count=2, minutes=50)],
            rules=[_rule(1, quantity=2, order=0), _rule(2, quantity=1, order=1)],
        )

        assert [data.value for _event_pk, data in repo.created] == [Decimal(50)]
        assert result == DiscountSyncResultDTO(
            marked=1, unmarked=0, discounts_set=1, discounts_cleared=0
        )

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

    def test_zero_percent_rule_shadows_the_rules_below_it(self):
        _result, repo, _facilitators, _change_logs = self._apply(
            list_items=[_list_item(pk=1, accreditation_type="none")],
            rows=[_load(1, minutes=240)],
            rules=[
                _rule(1, quantity=4, percent=0, order=0),
                _rule(2, quantity=1, percent=25, order=1),
            ],
        )

        assert not repo.created

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

    def test_rerun_updates_the_rule_discount_in_place(self):
        pk = 4
        percent = Decimal(75)
        result, repo, _facilitators, _change_logs = self._apply(
            list_items=[_list_item(pk=1, accreditation_type="creator")],
            rows=[_load(1, minutes=60)],
            rules=[_rule(1, quantity=1, percent=percent)],
            discounts=[_dto(pk, facilitator_id=1, from_rules=True)],
        )

        assert not repo.created
        assert repo.updated == [
            (
                pk,
                DiscountData(
                    facilitator_id=1,
                    kind=DiscountKind.PERCENT,
                    value=percent,
                    from_rules=True,
                ),
            )
        ]
        assert result.discounts_set == 1

    def test_unscheduled_creator_falls_back_to_no_accreditation(self):
        result, _repo, facilitators, change_logs = self._apply(
            list_items=[_list_item(pk=1, accreditation_type="creator")],
            rows=[],
            rules=[_rule(1)],
        )

        assert facilitators.accreditations == [(EVENT_PK, [1], "none")]
        assert change_logs.batches == [
            [
                {
                    "event_id": EVENT_PK,
                    "facilitator_id": 1,
                    "user_id": 7,
                    "changes": [
                        {
                            "field": "accreditation_type",
                            "field_id": None,
                            "old": "creator",
                            "new": "none",
                        }
                    ],
                }
            ]
        ]
        assert result == DiscountSyncResultDTO(
            marked=0, unmarked=1, discounts_set=0, discounts_cleared=0
        )


class TestRules:
    def test_rules_live_and_die_within_their_event(self):
        rules = FakeRules(rules=[_rule(1)])
        service = _service(rules=rules)
        data = DiscountRuleData(
            method=DiscountMethod.SESSION_COUNT,
            quantity=2,
            percent=Decimal(30),
            order=1,
        )

        created = service.create_rule(1, data)

        assert service.list_rules(1) == [_rule(1), created]
        assert service.read_rule(1, created.pk) == created
        assert service.read_rule(99, created.pk) is None
        assert service.update_rule(event_pk=99, pk=created.pk, data=data) is None
        assert service.update_rule(event_pk=1, pk=created.pk, data=data) == created
        assert service.delete_rule(99, created.pk) is False
        assert service.delete_rule(1, created.pk) is True
        assert service.list_rules(1) == [_rule(1)]


class TestScopedReads:
    def test_a_discount_of_another_event_is_not_found(self):
        service = _service(repo=FakeRepo(items=[_dto(4, event_id=2)]))

        with pytest.raises(NotFoundError):
            service.read_scoped(event_pk=1, pk=4)

    def test_a_discount_of_the_event_is_read(self):
        service = _service(repo=FakeRepo(items=[_dto(4)]))

        assert service.read_scoped(event_pk=1, pk=4) == _dto(4)

    def test_a_facilitator_of_another_event_is_not_found(self):
        facilitator = FacilitatorDTO(
            accreditation_type="none",
            display_name="Ada",
            event_id=2,
            pk=1,
            slug="ada",
            user_id=None,
        )
        service = _service(facilitators=FakeFacilitators(facilitator=facilitator))

        with pytest.raises(NotFoundError):
            service.read_scoped_facilitator(event_pk=1, facilitator_id=1)
        assert (
            service.read_scoped_facilitator(event_pk=2, facilitator_id=1) == facilitator
        )


class TestHandWrites:
    def test_create_update_and_soft_delete_reach_the_store(self):
        repo = FakeRepo()
        service = _service(repo=repo)
        data = DiscountData(
            facilitator_id=1,
            kind=DiscountKind.PERCENT,
            value=Decimal(10),
            from_rules=False,
        )

        created = service.create(1, data)
        updated = service.update(created.pk, data)
        service.soft_delete(created.pk)

        assert repo.created == [(1, data)]
        assert repo.updated == [(created.pk, data)]
        assert repo.soft_deleted == [created.pk]
        assert updated.pk == created.pk


class TestRoster:
    def test_pairs_each_facilitator_with_their_discount_or_none(self):
        service = _service(
            repo=FakeRepo(items=[_dto(4, facilitator_id=2)]),
            facilitators=FakeFacilitators(list_items=[_list_item(1), _list_item(2)]),
        )

        roster = service.list_roster(1)

        assert [(entry.facilitator.pk, entry.discount) for entry in roster] == [
            (1, None),
            (2, _dto(4, facilitator_id=2)),
        ]
