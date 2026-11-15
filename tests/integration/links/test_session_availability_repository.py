from datetime import timedelta

import pytest
from django.utils.timezone import get_current_timezone

from ludamus.links.db.django.repositories.sessions import SessionRepository
from ludamus.pacts.availability import AvailabilityDTO, DayPart, slot_availability
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.event import TimeSlotDTO
from tests.integration.conftest import (
    SessionAvailabilityFactory,
    SessionFactory,
    TimeSlotFactory,
)


def _offer(slot):
    return slot_availability(TimeSlotDTO.model_validate(slot), get_current_timezone())


class TestSetAvailability:
    def test_links_the_events_slots_and_drops_parts_no_longer_offered(self, event):
        session = SessionFactory(event=event)
        SessionAvailabilityFactory(session=session)
        slot = TimeSlotFactory(event=event)

        SessionRepository.set_availability(session.pk, [_offer(slot)])

        assert list(session.time_slots.all()) == [slot]
        assert not session.availability.exists()

    def test_refuses_another_events_slot_without_writing(self, event):
        session = SessionFactory(event=event)
        kept = SessionAvailabilityFactory(session=session)
        own = TimeSlotFactory(event=event)
        foreign = TimeSlotFactory()

        with pytest.raises(NotFoundError):
            SessionRepository.set_availability(
                session.pk, [_offer(own), _offer(foreign)]
            )

        assert not session.time_slots.exists()
        assert list(session.availability.all()) == [kept]


class TestReadAvailability:
    def test_reads_parts_and_slots_in_the_order_a_day_reads(self, event):
        session = SessionFactory(event=event)
        late = TimeSlotFactory(
            event=event,
            start_time=event.start_time + timedelta(days=1),
            end_time=event.start_time + timedelta(days=1, hours=2),
        )
        session.time_slots.add(late)
        part = SessionAvailabilityFactory(session=session)

        offered = SessionRepository.read_availability(session.pk)

        assert offered == [
            AvailabilityDTO(day=part.day, part=DayPart(part.part)),
            _offer(late),
        ]
