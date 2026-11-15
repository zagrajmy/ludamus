from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.links.db.django.models import (
    Event,
    EventDeletionApproval,
    Session,
    SphereMembership,
)
from ludamus.pacts.errors import NotFoundError
from ludamus.pacts.event_deletion import (
    EventDeletionApprovalDTO,
    EventDeletionRepositoryProtocol,
    EventDeletionTargetDTO,
)
from ludamus.pacts.ids import UserId
from ludamus.pacts.sphere import SphereRole

if TYPE_CHECKING:
    from datetime import datetime

    from django.db.models import QuerySet

    from ludamus.pacts.ids import EventId, SphereId


def _target(
    events: QuerySet[Event], *, sphere_id: SphereId, event_id: EventId
) -> EventDeletionTargetDTO:
    try:
        event = events.select_related("sphere__site").get(
            pk=event_id, sphere_id=sphere_id
        )
    except Event.DoesNotExist as exception:
        raise NotFoundError from exception
    return EventDeletionTargetDTO(
        pk=event.pk,
        name=event.name,
        slug=event.slug,
        sphere_domain=event.sphere.site.domain,
    )


class EventDeletionRepository(EventDeletionRepositoryProtocol):
    @staticmethod
    def read_event(*, sphere_id: SphereId, event_id: EventId) -> EventDeletionTargetDTO:
        return _target(Event.objects.all(), sphere_id=sphere_id, event_id=event_id)

    @staticmethod
    def lock_event(*, sphere_id: SphereId, event_id: EventId) -> EventDeletionTargetDTO:
        return _target(
            Event.objects.select_for_update(of=("self",)),
            sphere_id=sphere_id,
            event_id=event_id,
        )

    @staticmethod
    def manager_ids(sphere_id: SphereId) -> frozenset[UserId]:
        return frozenset(
            UserId(user_id)
            for user_id in SphereMembership.objects.filter(
                sphere_id=sphere_id, role=SphereRole.MANAGER
            ).values_list("user_id", flat=True)
        )

    @staticmethod
    def list_approvals(event_id: EventId) -> list[EventDeletionApprovalDTO]:
        approvals = (
            EventDeletionApproval.objects.filter(event_id=event_id)
            .select_related("user")
            .order_by("creation_time", "pk")
        )
        return [
            EventDeletionApprovalDTO(
                user_id=approval.user_id,
                user_name=approval.user.full_name,
                approved_at=approval.creation_time,
            )
            for approval in approvals
        ]

    @staticmethod
    def add_approval(*, event_id: EventId, user_id: UserId) -> None:
        EventDeletionApproval.objects.get_or_create(event_id=event_id, user_id=user_id)

    @staticmethod
    def remove_approval(*, event_id: EventId, user_id: UserId) -> None:
        EventDeletionApproval.objects.filter(
            event_id=event_id, user_id=user_id
        ).delete()

    @staticmethod
    def soft_delete_event(*, event_id: EventId, at: datetime) -> None:
        Session.objects.filter(event_id=event_id).update(deleted_at=at)
        Event.objects.filter(pk=event_id).update(deleted_at=at)

    @staticmethod
    def restore_event(event_id: EventId) -> None:
        """Bring a deleted event back with the sessions its deletion hid.

        Its approvals go, so deleting it again takes a fresh vote.
        """
        stamp = (
            Event.all_objects.filter(pk=event_id)
            .values_list("deleted_at", flat=True)
            .first()
        )
        if stamp is None:
            return
        Session.all_objects.filter(event_id=event_id, deleted_at=stamp).update(
            deleted_at=None
        )
        EventDeletionApproval.objects.filter(event_id=event_id).delete()
        Event.all_objects.filter(pk=event_id).update(deleted_at=None)
