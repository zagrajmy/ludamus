from datetime import UTC, datetime

import pytest

from ludamus.links.db.django.event_deletion import EventDeletionRepository
from ludamus.links.db.django.models import Event, EventDeletionApproval
from ludamus.pacts.errors import NotFoundError
from tests.integration.conftest import EventFactory, SphereFactory, UserFactory


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
