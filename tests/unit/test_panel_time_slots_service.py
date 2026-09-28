from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from ludamus.mills.panel_time_slots import PanelTimeSlotsService
from ludamus.pacts import EventDTO, NotFoundError, TimeSlotDTO
from ludamus.pacts.event import TimeSlotRejectedError, TimeSlotValidationError

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

        saved = service.create(
            event=_event(),
            start_time=datetime(2026, 6, 3, 21, 0, tzinfo=UTC),
            end_time=end,
        )

        assert saved.event_dates_widened is False
        events.lock.assert_called_once_with(_EVENT_ID)
        events.update.assert_not_called()

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
