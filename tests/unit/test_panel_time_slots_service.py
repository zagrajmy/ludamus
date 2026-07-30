from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from ludamus.mills.panel_time_slots import PanelTimeSlotsService
from ludamus.pacts import EventDTO, NotFoundError, TimeSlotDTO
from ludamus.pacts.event import TimeSlotValidationError

_EVENT_ID = 42


def _event(pk=_EVENT_ID):
    return EventDTO(
        description="",
        end_time=datetime(2026, 6, 3, 18, 0, tzinfo=UTC),
        name="Konwent",
        pk=pk,
        proposal_end_time=None,
        proposal_start_time=None,
        publication_time=None,
        slug="konwent",
        sphere_id=1,
        start_time=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
    )


def _slot(pk=1, hour_start=10, hour_end=12):
    return TimeSlotDTO(
        pk=pk,
        start_time=datetime(2026, 6, 1, hour_start, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, 1, hour_end, 0, tzinfo=UTC),
    )


class TestPanelTimeSlotsService:
    @pytest.fixture
    def time_slots(self):
        return MagicMock()

    @pytest.fixture
    def transaction(self):
        return MagicMock()

    @pytest.fixture
    def service(self, transaction, time_slots):
        return PanelTimeSlotsService(transaction=transaction, time_slots=time_slots)

    def test_list_for_event_delegates_to_repo(self, service, time_slots):
        slots = [_slot(pk=1), _slot(pk=2, hour_start=13, hour_end=14)]
        time_slots.list_by_event.return_value = slots

        result = service.list_for_event(_EVENT_ID)

        assert result is slots
        time_slots.list_by_event.assert_called_once_with(_EVENT_ID)

    def test_read_scopes_pk_to_event(self, service, time_slots):
        slot = _slot(pk=7)
        time_slots.read_by_event.return_value = slot

        result = service.read(event_id=_EVENT_ID, pk=7)

        assert result is slot
        time_slots.read_by_event.assert_called_once_with(_EVENT_ID, 7)

    def test_read_propagates_not_found_for_foreign_pk(self, service, time_slots):
        time_slots.read_by_event.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.read(event_id=_EVENT_ID, pk=999)

    def test_create_persists_valid_slot_in_transaction(
        self, service, transaction, time_slots
    ):
        time_slots.list_by_event.return_value = [_slot(pk=1)]
        start = datetime(2026, 6, 1, 13, 0, tzinfo=UTC)
        end = datetime(2026, 6, 1, 15, 0, tzinfo=UTC)

        errors = service.create(event=_event(), start_time=start, end_time=end)

        assert errors == []
        transaction.atomic.assert_called_once_with()
        time_slots.list_by_event.assert_called_once_with(_EVENT_ID)
        time_slots.create.assert_called_once_with(_EVENT_ID, start, end)

    def test_create_returns_errors_without_writing(self, service, time_slots):
        time_slots.list_by_event.return_value = [_slot(pk=1)]
        start = datetime(2026, 6, 1, 11, 0, tzinfo=UTC)
        end = datetime(2026, 6, 1, 13, 0, tzinfo=UTC)

        errors = service.create(event=_event(), start_time=start, end_time=end)

        assert errors == [TimeSlotValidationError.OVERLAPS_EXISTING_SLOT]
        time_slots.create.assert_not_called()

    def test_create_returns_outside_event_dates_for_slot_before_event(
        self, service, time_slots
    ):
        time_slots.list_by_event.return_value = [_slot(pk=1)]
        start = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
        end = datetime(2026, 6, 1, 9, 30, tzinfo=UTC)

        errors = service.create(event=_event(), start_time=start, end_time=end)

        assert errors == [TimeSlotValidationError.OUTSIDE_EVENT_DATES]
        time_slots.create.assert_not_called()

    def test_create_accumulates_every_broken_rule(self, service, time_slots):
        time_slots.list_by_event.return_value = [_slot(pk=1)]
        start = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
        end = datetime(2026, 6, 1, 7, 0, tzinfo=UTC)

        errors = service.create(event=_event(), start_time=start, end_time=end)

        assert errors == [
            TimeSlotValidationError.START_NOT_BEFORE_END,
            TimeSlotValidationError.OUTSIDE_EVENT_DATES,
        ]
        time_slots.create.assert_not_called()

    def test_update_persists_valid_slot_scoped_to_event(
        self, service, transaction, time_slots
    ):
        time_slots.read_by_event.return_value = _slot(pk=1)
        time_slots.list_by_event.return_value = [
            _slot(pk=1),
            _slot(pk=2, hour_start=13, hour_end=14),
        ]
        start = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
        end = datetime(2026, 6, 1, 12, 30, tzinfo=UTC)

        errors = service.update(event=_event(), pk=1, start_time=start, end_time=end)

        assert errors == []
        transaction.atomic.assert_called_once_with()
        time_slots.read_by_event.assert_called_once_with(_EVENT_ID, 1)
        time_slots.update.assert_called_once_with(1, start, end)

    def test_update_ignores_own_slot_when_checking_overlap(self, service, time_slots):
        time_slots.read_by_event.return_value = _slot(pk=1)
        time_slots.list_by_event.return_value = [_slot(pk=1)]
        start = datetime(2026, 6, 1, 10, 30, tzinfo=UTC)
        end = datetime(2026, 6, 1, 11, 30, tzinfo=UTC)

        errors = service.update(event=_event(), pk=1, start_time=start, end_time=end)

        assert errors == []
        time_slots.update.assert_called_once_with(1, start, end)

    def test_update_returns_errors_without_writing(self, service, time_slots):
        time_slots.read_by_event.return_value = _slot(pk=1)
        time_slots.list_by_event.return_value = [_slot(pk=1)]
        start = datetime(2026, 6, 1, 15, 0, tzinfo=UTC)
        end = datetime(2026, 6, 1, 14, 0, tzinfo=UTC)

        errors = service.update(event=_event(), pk=1, start_time=start, end_time=end)

        assert errors == [TimeSlotValidationError.START_NOT_BEFORE_END]
        time_slots.update.assert_not_called()

    def test_update_foreign_pk_raises_without_side_effects(self, service, time_slots):
        time_slots.read_by_event.side_effect = NotFoundError
        start = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
        end = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

        with pytest.raises(NotFoundError):
            service.update(event=_event(), pk=999, start_time=start, end_time=end)

        time_slots.update.assert_not_called()

    def test_delete_removes_unused_slot_in_transaction(
        self, service, transaction, time_slots
    ):
        time_slots.read_by_event.return_value = _slot(pk=5)
        time_slots.has_proposals.return_value = False

        deleted = service.delete(event_id=_EVENT_ID, pk=5)

        assert deleted is True
        transaction.atomic.assert_called_once_with()
        time_slots.read_by_event.assert_called_once_with(_EVENT_ID, 5)
        time_slots.has_proposals.assert_called_once_with(5)
        time_slots.delete.assert_called_once_with(5)

    def test_delete_refuses_slot_with_proposals(self, service, time_slots):
        time_slots.read_by_event.return_value = _slot(pk=5)
        time_slots.has_proposals.return_value = True

        deleted = service.delete(event_id=_EVENT_ID, pk=5)

        assert deleted is False
        time_slots.delete.assert_not_called()

    def test_delete_foreign_pk_raises_without_side_effects(self, service, time_slots):
        time_slots.read_by_event.side_effect = NotFoundError

        with pytest.raises(NotFoundError):
            service.delete(event_id=_EVENT_ID, pk=999)

        time_slots.has_proposals.assert_not_called()
        time_slots.delete.assert_not_called()
