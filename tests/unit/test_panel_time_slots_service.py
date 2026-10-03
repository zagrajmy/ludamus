from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from ludamus.mills.panel_time_slots import PanelTimeSlotsService
from ludamus.pacts import NotFoundError, TimeSlotDTO
from ludamus.pacts.event import (
    TimeSlotRejectedError,
    TimeSlotSavedDTO,
    TimeSlotValidationError,
)
from tests.unit.factories import event_dto

_EVENT_ID = 42


def _event(pk=_EVENT_ID):
    return event_dto(end_time=datetime(2026, 6, 3, 18, 0, tzinfo=UTC), pk=pk)


def _slot(pk=1):
    return TimeSlotDTO(
        pk=pk,
        start_time=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )


class TestPanelTimeSlotsService:
    @pytest.fixture
    def time_slots(self):
        repo = MagicMock()
        repo.create.return_value = _slot(pk=9)
        repo.update.return_value = _slot(pk=1)
        return repo

    @pytest.fixture
    def events(self):
        repo = MagicMock()
        repo.read.return_value = _event()
        return repo

    @pytest.fixture
    def transaction(self):
        return MagicMock()

    @pytest.fixture
    def service(self, transaction, time_slots, events):
        return PanelTimeSlotsService(
            transaction=transaction, time_slots=time_slots, events=events
        )

    def test_create_widens_from_the_locked_row_not_the_callers_copy(
        self, service, time_slots, events
    ):
        time_slots.list_by_event.return_value = []
        end = datetime(2026, 6, 3, 23, 0, tzinfo=UTC)
        events.read.return_value = _event().model_copy(update={"end_time": end})

        start = datetime(2026, 6, 3, 21, 0, tzinfo=UTC)

        saved = service.create(event=_event(), start_time=start, end_time=end)

        assert saved == TimeSlotSavedDTO(slot=_slot(pk=9), event_dates_widened=False)
        time_slots.list_by_event.assert_called_once_with(_EVENT_ID)
        time_slots.create.assert_called_once_with(_EVENT_ID, start, end)
        events.lock.assert_called_once_with(_EVENT_ID)
        events.update.assert_not_called()

    def test_create_rejects_a_slot_ending_when_it_starts(self, service, time_slots):
        time_slots.list_by_event.return_value = []
        instant = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)

        with pytest.raises(TimeSlotRejectedError) as excinfo:
            service.create(event=_event(), start_time=instant, end_time=instant)

        assert excinfo.value.errors == [TimeSlotValidationError.START_NOT_BEFORE_END]
        time_slots.create.assert_not_called()

    def test_create_accepts_a_slot_touching_its_neighbours(self, service, time_slots):
        time_slots.list_by_event.return_value = [
            _slot(pk=1),
            TimeSlotDTO(
                pk=2,
                start_time=datetime(2026, 6, 1, 14, 0, tzinfo=UTC),
                end_time=datetime(2026, 6, 1, 16, 0, tzinfo=UTC),
            ),
        ]
        start = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        end = datetime(2026, 6, 1, 14, 0, tzinfo=UTC)

        saved = service.create(event=_event(), start_time=start, end_time=end)

        assert saved == TimeSlotSavedDTO(slot=_slot(pk=9), event_dates_widened=False)
        time_slots.create.assert_called_once_with(_EVENT_ID, start, end)

    def test_create_accumulates_every_broken_rule(self, service, time_slots):
        time_slots.list_by_event.return_value = [_slot(pk=1)]
        start = datetime(2026, 6, 1, 11, 0, tzinfo=UTC)
        end = datetime(2026, 6, 1, 10, 30, tzinfo=UTC)

        with pytest.raises(TimeSlotRejectedError) as excinfo:
            service.create(event=_event(), start_time=start, end_time=end)

        assert excinfo.value.errors == [
            TimeSlotValidationError.START_NOT_BEFORE_END,
            TimeSlotValidationError.OVERLAPS_EXISTING_SLOT,
        ]
        time_slots.create.assert_not_called()

    def test_update_foreign_pk_raises_without_side_effects(self, service, time_slots):
        time_slots.read_by_event.side_effect = NotFoundError
        start = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
        end = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

        with pytest.raises(NotFoundError):
            service.update(event=_event(), pk=999, start_time=start, end_time=end)

        time_slots.update.assert_not_called()

    def test_list_read_and_undeletable_pks_come_from_the_repo(
        self, service, time_slots
    ):
        time_slots.list_by_event.return_value = [_slot(pk=1)]
        time_slots.pks_with_proposals.return_value = frozenset({1})
        time_slots.read_by_event.return_value = _slot(pk=1)

        assert service.list_for_event(_EVENT_ID) == [_slot(pk=1)]
        assert service.undeletable_pks(_EVENT_ID) == frozenset({1})
        assert service.read(event_id=_EVENT_ID, pk=1) == _slot(pk=1)
        time_slots.list_by_event.assert_called_once_with(_EVENT_ID)
        time_slots.pks_with_proposals.assert_called_once_with(_EVENT_ID)
        time_slots.read_by_event.assert_called_once_with(_EVENT_ID, 1)

    def test_create_before_publication_is_rejected(self, service, time_slots, events):
        time_slots.list_by_event.return_value = []
        events.read.return_value = _event().model_copy(
            update={"publication_time": datetime(2026, 5, 31, 0, 0, tzinfo=UTC)}
        )

        with pytest.raises(TimeSlotRejectedError) as excinfo:
            service.create(
                event=_event(),
                start_time=datetime(2026, 5, 30, 9, 0, tzinfo=UTC),
                end_time=datetime(2026, 5, 30, 11, 0, tzinfo=UTC),
            )

        assert excinfo.value.errors == [
            TimeSlotValidationError.STARTS_BEFORE_PUBLICATION
        ]
        time_slots.create.assert_not_called()

    def test_update_ignores_the_slots_own_range_and_widens_the_event(
        self, service, time_slots, events
    ):
        time_slots.list_by_event.return_value = [_slot(pk=1), _slot(pk=2)]
        time_slots.read_by_event.return_value = _slot(pk=1)
        start = datetime(2026, 6, 3, 19, 0, tzinfo=UTC)
        end = datetime(2026, 6, 3, 20, 0, tzinfo=UTC)

        saved = service.update(event=_event(), pk=1, start_time=start, end_time=end)

        assert saved == TimeSlotSavedDTO(slot=_slot(pk=1), event_dates_widened=True)
        time_slots.read_by_event.assert_called_once_with(_EVENT_ID, 1)
        time_slots.list_by_event.assert_called_once_with(_EVENT_ID)
        time_slots.update.assert_called_once_with(1, start, end)
        events.lock.assert_called_once_with(_EVENT_ID)
        events.update.assert_called_once_with(_EVENT_ID, {"end_time": end})

    def test_update_may_overlap_the_slots_own_old_range(self, service, time_slots):
        time_slots.list_by_event.return_value = [
            _slot(pk=1),
            TimeSlotDTO(
                pk=2,
                start_time=datetime(2026, 6, 1, 14, 0, tzinfo=UTC),
                end_time=datetime(2026, 6, 1, 16, 0, tzinfo=UTC),
            ),
        ]
        time_slots.read_by_event.return_value = _slot(pk=1)
        start = datetime(2026, 6, 1, 11, 0, tzinfo=UTC)
        end = datetime(2026, 6, 1, 13, 0, tzinfo=UTC)

        saved = service.update(event=_event(), pk=1, start_time=start, end_time=end)

        assert saved == TimeSlotSavedDTO(slot=_slot(pk=1), event_dates_widened=False)
        time_slots.update.assert_called_once_with(1, start, end)

    def test_update_rejects_overlap_with_another_slot(self, service, time_slots):
        time_slots.list_by_event.return_value = [_slot(pk=1), _slot(pk=2)]
        time_slots.read_by_event.return_value = _slot(pk=1)

        with pytest.raises(TimeSlotRejectedError) as excinfo:
            service.update(
                event=_event(),
                pk=1,
                start_time=datetime(2026, 6, 1, 11, 0, tzinfo=UTC),
                end_time=datetime(2026, 6, 1, 13, 0, tzinfo=UTC),
            )

        assert excinfo.value.errors == [TimeSlotValidationError.OVERLAPS_EXISTING_SLOT]
        time_slots.update.assert_not_called()

    def test_delete_refuses_a_slot_with_proposals(self, service, time_slots):
        time_slots.has_proposals.return_value = True

        assert service.delete(event_id=_EVENT_ID, pk=1) is False
        time_slots.read_by_event.assert_called_once_with(_EVENT_ID, 1)
        time_slots.has_proposals.assert_called_once_with(1)
        time_slots.delete.assert_not_called()

    def test_delete_removes_a_free_slot(self, service, time_slots):
        time_slots.has_proposals.return_value = False

        assert service.delete(event_id=_EVENT_ID, pk=1) is True
        time_slots.read_by_event.assert_called_once_with(_EVENT_ID, 1)
        time_slots.has_proposals.assert_called_once_with(1)
        time_slots.delete.assert_called_once_with(1)
