from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event as Pause
from time import monotonic

import pytest
from django.db import connection, transaction

from ludamus.links.db.django.event_deletion import EventDeletionRepository
from ludamus.links.db.django.models import Event, EventDeletionApproval, Session
from ludamus.pacts.errors import NotFoundError
from tests.integration.conftest import (
    EventFactory,
    SessionFactory,
    SphereFactory,
    UserFactory,
)


def _wait_until_blocked_by_this_transaction(future):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE NOT granted"
                " AND pg_backend_pid() = ANY(pg_blocking_pids(pid)))"
            )
            if cursor.fetchone() == (True,):
                return
        if future.done():
            future.result()
            pytest.fail("The restore finished without waiting for the held event")
        Pause().wait(0.01)
    pytest.fail("The restore never reached the held event row")


@pytest.mark.django_db
class TestEventDeletionRepository:
    def test_another_spheres_event_is_not_found(self, event):
        with pytest.raises(NotFoundError):
            EventDeletionRepository.read_event(
                sphere_id=SphereFactory().pk, event_id=event.pk
            )

    def test_a_deleted_event_cannot_be_locked_for_another_vote(self, sphere):
        deleted = EventFactory(sphere=sphere)
        EventDeletionRepository.soft_delete_event(
            event_id=deleted.pk, at=datetime.now(UTC)
        )

        with pytest.raises(NotFoundError):
            EventDeletionRepository.lock_event(sphere_id=sphere.pk, event_id=deleted.pk)

    def test_restoring_a_live_event_keeps_its_vote(self, event):
        # Restoring clears approvals so a deleted event starts a fresh vote;
        # an event that was never deleted must keep the vote it has.
        manager = UserFactory()
        EventDeletionApproval.objects.create(event=event, user=manager)

        EventDeletionRepository.restore_event(event.pk)

        assert EventDeletionApproval.objects.filter(event=event).exists()
        assert Event.objects.filter(pk=event.pk).exists()

    def test_a_restore_leaves_another_events_sessions_deleted(self, sphere):
        at = datetime(2026, 11, 1, 12, tzinfo=UTC)
        restored, other = EventFactory(sphere=sphere), EventFactory(sphere=sphere)
        own_session = SessionFactory(event=restored, category=None)
        other_session = SessionFactory(event=other, category=None)
        for deleted in (restored, other):
            EventDeletionRepository.soft_delete_event(event_id=deleted.pk, at=at)

        with transaction.atomic():
            EventDeletionRepository.restore_event(restored.pk)

        assert Session.objects.filter(pk=own_session.pk).exists()
        assert Session.all_objects.get(pk=other_session.pk).deleted_at == at


@pytest.mark.postgres
@pytest.mark.usefixtures("transactional_db")
def test_a_restore_waits_for_a_deletion_that_holds_the_event():
    # Two restores read the same stamp; the first commits and the managers
    # delete the event again. The second must not then clear the new stamp
    # without the sessions it hid. The open transaction below stands for that
    # first restore and the new deletion; the thread is the second restore.
    event = EventFactory()
    session = SessionFactory(event=event, category=None)
    first = datetime(2026, 11, 1, 12, tzinfo=UTC)
    second = datetime(2026, 11, 2, 12, tzinfo=UTC)
    EventDeletionRepository.soft_delete_event(event_id=event.pk, at=first)

    def restore():
        try:
            with transaction.atomic():
                EventDeletionRepository.restore_event(event.pk)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            Event.all_objects.select_for_update().get(pk=event.pk)
            Session.all_objects.filter(pk=session.pk).update(deleted_at=second)
            Event.all_objects.filter(pk=event.pk).update(deleted_at=second)
            restoring = pool.submit(restore)
            _wait_until_blocked_by_this_transaction(restoring)
        restoring.result()

    assert Event.objects.filter(pk=event.pk).exists()
    assert Session.objects.filter(pk=session.pk).exists()
