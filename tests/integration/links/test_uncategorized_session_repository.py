"""An event without proposal categories still owns the sessions proposed to it.

Session.category is nullable, and the public wizard leaves it empty when the
event has no categories, so every panel query has to reach a session through
its own event, not through its category.
"""

import pytest

from ludamus.links.db.django.models import Session
from ludamus.links.db.django.repositories.event import EventRepository
from ludamus.links.db.django.repositories.sessions import SessionRepository
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.sessions import SessionStatus
from ludamus.pacts.timetable import UnscheduledSessionFilter
from tests.integration.conftest import EventFactory, SessionFactory


@pytest.fixture(name="uncategorized")
def uncategorized_fixture() -> Session:
    return SessionFactory(category=None, event=EventFactory(), status="pending")


class TestUncategorizedSessions:
    def test_the_panel_list_includes_it(self, uncategorized):
        listed = SessionRepository.list_sessions_by_event(uncategorized.event_id)

        assert [item.pk for item in listed] == [uncategorized.pk]

    def test_a_scoped_read_finds_it(self, uncategorized):
        read = SessionRepository.read_by_event(uncategorized.pk, uncategorized.event_id)

        assert read.pk == uncategorized.pk

    def test_a_scoped_read_from_another_event_does_not(self, uncategorized):
        other = EventFactory()

        with pytest.raises(NotFoundError):
            SessionRepository.read_by_event(uncategorized.pk, other.pk)

    def test_the_timetable_offers_it_once_accepted(self, uncategorized):
        uncategorized.status = SessionStatus.ACCEPTED
        uncategorized.save()

        unscheduled, _ = SessionRepository.list_unscheduled_by_event(
            uncategorized.event_id, UnscheduledSessionFilter()
        )

        assert [item.pk for item in unscheduled] == [uncategorized.pk]

    def test_it_can_be_restored_from_the_bin(self, uncategorized):
        SessionRepository.soft_delete(uncategorized.pk)

        binned = SessionRepository.list_deleted_by_event(uncategorized.event_id)
        SessionRepository.restore(uncategorized.pk, uncategorized.event_id)

        assert [item.pk for item in binned] == [uncategorized.pk]
        assert Session.objects.filter(pk=uncategorized.pk).exists()

    def test_the_panel_stats_count_it(self, uncategorized):
        stats = EventRepository.get_stats_data(uncategorized.event_id)

        assert (stats.pending_proposals, stats.total_proposals) == (1, 1)
