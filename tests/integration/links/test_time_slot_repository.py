from datetime import UTC, datetime, timedelta

from ludamus.adapters.db.django.models import TimeSlot
from ludamus.links.db.django.repositories import TimeSlotRepository
from tests.integration.conftest import EventFactory


class TestTimeSlotRepositoryGetOrCreate:
    def test_reuses_an_existing_window(self):
        event = EventFactory.create()
        start = datetime.now(UTC)
        end = start + timedelta(hours=2)
        first = TimeSlotRepository.get_or_create(event.pk, start, end)

        second = TimeSlotRepository.get_or_create(event.pk, start, end)

        assert second == first
        assert TimeSlot.objects.filter(event=event).count() == 1

    def test_creates_distinct_windows(self):
        event = EventFactory.create()
        start = datetime.now(UTC)
        first = TimeSlotRepository.get_or_create(
            event.pk, start, start + timedelta(hours=2)
        )

        second = TimeSlotRepository.get_or_create(
            event.pk, start + timedelta(hours=3), start + timedelta(hours=5)
        )

        assert second != first
        assert set(
            TimeSlot.objects.filter(event=event).values_list("pk", flat=True)
        ) == {first, second}
