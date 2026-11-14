from datetime import UTC, datetime

import pytest

from ludamus.mills.event import PanelTimeSlotsService
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.event import (
    TimeSlotDTO,
    TimeSlotRejectedError,
    TimeSlotSavedDTO,
    TimeSlotValidationError,
)
from tests.unit.factories import FakeTransaction, event_dto

_EVENT_ID = 42
_OTHER_EVENT_ID = 43


def _at(day, hour, minute=0):
    return datetime(2026, 6, day, hour, minute, tzinfo=UTC)


def _callers_copy():
    # NOTE: the panel hands the service its own copy of the event; the
    # service must widen from the locked row, never from this one.
    return event_dto(pk=_EVENT_ID, start_time=_at(1, 9), end_time=_at(3, 18))


class FakeTimeSlots:
    def __init__(self):
        self.rows: dict[int, tuple[int, TimeSlotDTO]] = {}
        self.with_proposals: set[int] = set()

    def add(self, event_id, start, end):
        pk = len(self.rows) + 1
        self.rows[pk] = (event_id, TimeSlotDTO(pk=pk, start_time=start, end_time=end))
        return pk

    def slots(self, event_id=_EVENT_ID):
        return [slot for owner, slot in self.rows.values() if owner == event_id]

    def list_by_event(self, event_id):
        return self.slots(event_id)

    def pks_with_proposals(self, event_id):
        return frozenset(
            slot.pk for slot in self.slots(event_id) if slot.pk in self.with_proposals
        )

    def read_by_event(self, event_id, pk):
        owner, slot = self.rows.get(pk, (None, None))
        if owner != event_id:
            raise NotFoundError
        return slot

    def create(self, event_id, start, end):
        return self.rows[self.add(event_id, start, end)][1]

    def update(self, pk, start, end):
        owner, _ = self.rows[pk]
        self.rows[pk] = (owner, TimeSlotDTO(pk=pk, start_time=start, end_time=end))
        return self.rows[pk][1]

    def has_proposals(self, pk):
        return pk in self.with_proposals

    def delete(self, pk):
        del self.rows[pk]


class FakeEvents:
    def __init__(self, event):
        self.event = event
        self.locked: list[int] = []

    def lock(self, pk):
        self.locked.append(pk)

    def read(self, pk):
        assert pk == self.event.pk
        return self.event

    def update(self, pk, data):
        assert pk == self.event.pk
        self.event = self.event.model_copy(update=data)


@pytest.fixture(name="time_slots")
def time_slots_fixture():
    return FakeTimeSlots()


@pytest.fixture(name="events")
def events_fixture():
    return FakeEvents(
        event_dto(pk=_EVENT_ID, start_time=_at(1, 9), end_time=_at(3, 18))
    )


@pytest.fixture(name="service")
def service_fixture(time_slots, events):
    return PanelTimeSlotsService(
        transaction=FakeTransaction(), time_slots=time_slots, events=events
    )


class TestCreate:
    def test_a_created_slot_is_listed_and_readable(self, service):
        saved = service.create(
            event=_callers_copy(), start_time=_at(1, 10), end_time=_at(1, 12)
        )

        assert saved.event_dates_widened is False
        assert service.list_for_event(_EVENT_ID) == [saved.slot]
        assert service.read(event_id=_EVENT_ID, pk=saved.slot.pk) == saved.slot
        assert (saved.slot.start_time, saved.slot.end_time) == (_at(1, 10), _at(1, 12))

    def test_create_widens_from_the_locked_row_not_the_callers_copy(
        self, service, events
    ):
        # The caller's copy still ends at 18:00, but the row already grew to
        # 23:00: a slot ending then must not shrink it back or report widening.
        events.event = events.event.model_copy(update={"end_time": _at(3, 23)})

        saved = service.create(
            event=_callers_copy(), start_time=_at(3, 21), end_time=_at(3, 23)
        )

        assert saved.event_dates_widened is False
        assert events.event.end_time == _at(3, 23)
        assert events.locked == [_EVENT_ID]

    def test_create_past_the_event_end_widens_it(self, service, events):
        saved = service.create(
            event=_callers_copy(), start_time=_at(4, 10), end_time=_at(4, 12)
        )

        assert saved.event_dates_widened is True
        assert events.event.end_time == _at(4, 12)

    def test_create_rejects_a_slot_ending_when_it_starts(self, service, time_slots):
        with pytest.raises(TimeSlotRejectedError) as excinfo:
            service.create(
                event=_callers_copy(), start_time=_at(1, 10), end_time=_at(1, 10)
            )

        assert excinfo.value.errors == [TimeSlotValidationError.START_NOT_BEFORE_END]
        assert not time_slots.rows

    def test_create_accepts_a_slot_touching_its_neighbours(self, service, time_slots):
        time_slots.add(_EVENT_ID, _at(1, 10), _at(1, 12))
        time_slots.add(_EVENT_ID, _at(1, 14), _at(1, 16))

        service.create(
            event=_callers_copy(), start_time=_at(1, 12), end_time=_at(1, 14)
        )

        assert [slot.start_time for slot in time_slots.slots()] == [
            _at(1, 10),
            _at(1, 14),
            _at(1, 12),
        ]

    def test_create_ignores_slots_of_other_events(self, service, time_slots):
        time_slots.add(_OTHER_EVENT_ID, _at(1, 10), _at(1, 12))

        service.create(
            event=_callers_copy(), start_time=_at(1, 10), end_time=_at(1, 12)
        )

        assert len(time_slots.slots()) == 1

    def test_create_accumulates_every_broken_rule(self, service, time_slots):
        time_slots.add(_EVENT_ID, _at(1, 10), _at(1, 12))

        with pytest.raises(TimeSlotRejectedError) as excinfo:
            service.create(
                event=_callers_copy(), start_time=_at(1, 11), end_time=_at(1, 10, 30)
            )

        assert excinfo.value.errors == [
            TimeSlotValidationError.START_NOT_BEFORE_END,
            TimeSlotValidationError.OVERLAPS_EXISTING_SLOT,
        ]
        assert len(time_slots.rows) == 1

    def test_create_before_publication_is_rejected(self, service, time_slots, events):
        events.event = events.event.model_copy(
            update={"publication_time": datetime(2026, 5, 31, tzinfo=UTC)}
        )

        with pytest.raises(TimeSlotRejectedError) as excinfo:
            service.create(
                event=_callers_copy(),
                start_time=datetime(2026, 5, 30, 9, tzinfo=UTC),
                end_time=datetime(2026, 5, 30, 11, tzinfo=UTC),
            )

        assert excinfo.value.errors == [
            TimeSlotValidationError.STARTS_BEFORE_PUBLICATION
        ]
        assert not time_slots.rows
        assert events.event.start_time == _at(1, 9)


class TestUpdate:
    def test_update_foreign_pk_raises_without_side_effects(self, service, time_slots):
        foreign = time_slots.add(_OTHER_EVENT_ID, _at(1, 10), _at(1, 12))
        before = dict(time_slots.rows)

        with pytest.raises(NotFoundError):
            service.update(
                event=_callers_copy(),
                pk=foreign,
                start_time=_at(1, 14),
                end_time=_at(1, 16),
            )

        assert time_slots.rows == before

    def test_update_ignores_the_slots_own_range_and_widens_the_event(
        self, service, time_slots, events
    ):
        own = time_slots.add(_EVENT_ID, _at(1, 10), _at(1, 12))

        saved = service.update(
            event=_callers_copy(), pk=own, start_time=_at(3, 19), end_time=_at(3, 20)
        )

        assert saved == TimeSlotSavedDTO(
            slot=TimeSlotDTO(pk=own, start_time=_at(3, 19), end_time=_at(3, 20)),
            event_dates_widened=True,
        )
        assert events.event.end_time == _at(3, 20)
        assert events.locked == [_EVENT_ID]

    def test_update_may_overlap_the_slots_own_old_range(self, service, time_slots):
        own = time_slots.add(_EVENT_ID, _at(1, 10), _at(1, 12))
        time_slots.add(_EVENT_ID, _at(1, 14), _at(1, 16))

        saved = service.update(
            event=_callers_copy(), pk=own, start_time=_at(1, 11), end_time=_at(1, 13)
        )

        assert saved.event_dates_widened is False
        assert service.read(event_id=_EVENT_ID, pk=own).start_time == _at(1, 11)

    def test_update_rejects_overlap_with_another_slot(self, service, time_slots):
        own = time_slots.add(_EVENT_ID, _at(1, 8), _at(1, 9))
        time_slots.add(_EVENT_ID, _at(1, 10), _at(1, 12))

        with pytest.raises(TimeSlotRejectedError) as excinfo:
            service.update(
                event=_callers_copy(),
                pk=own,
                start_time=_at(1, 11),
                end_time=_at(1, 13),
            )

        assert excinfo.value.errors == [TimeSlotValidationError.OVERLAPS_EXISTING_SLOT]
        assert time_slots.rows[own][1].start_time == _at(1, 8)


class TestDelete:
    def test_delete_refuses_a_slot_with_proposals(self, service, time_slots):
        asked_for = time_slots.add(_EVENT_ID, _at(1, 10), _at(1, 12))
        time_slots.with_proposals.add(asked_for)

        assert service.undeletable_pks(_EVENT_ID) == frozenset({asked_for})
        assert service.delete(event_id=_EVENT_ID, pk=asked_for) is False
        assert asked_for in time_slots.rows

    def test_delete_removes_a_free_slot(self, service, time_slots):
        free = time_slots.add(_EVENT_ID, _at(1, 10), _at(1, 12))

        assert service.undeletable_pks(_EVENT_ID) == frozenset()
        assert service.delete(event_id=_EVENT_ID, pk=free) is True
        assert not time_slots.rows

    def test_delete_of_a_foreign_slot_raises_and_keeps_it(self, service, time_slots):
        foreign = time_slots.add(_OTHER_EVENT_ID, _at(1, 10), _at(1, 12))

        with pytest.raises(NotFoundError):
            service.delete(event_id=_EVENT_ID, pk=foreign)

        assert foreign in time_slots.rows
