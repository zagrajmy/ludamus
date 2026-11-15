from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.pacts.event_deletion import (
    EventDeletionBallotDTO,
    EventDeletionOutcome,
    EventDeletionRequestedNotification,
    EventDeletionServiceProtocol,
    NotSphereManagerError,
)
from ludamus.specs.event_deletion import approvals_needed

if TYPE_CHECKING:
    from ludamus.pacts.event_deletion import (
        EventDeletionApprovalDTO,
        EventDeletionNotifierProtocol,
        EventDeletionRepositoryProtocol,
        EventDeletionTargetDTO,
    )
    from ludamus.pacts.ids import EventId, SphereId, UserId
    from ludamus.pacts.services import TransactionProtocol

logger = logging.getLogger(__name__)


class EventDeletionService(EventDeletionServiceProtocol):
    """Deletes an event once enough of its sphere's managers approve.

    Only approvals from people who manage the sphere now are counted: someone
    who approved and then left the team no longer speaks for it.
    """

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        repository: EventDeletionRepositoryProtocol,
        notifier: EventDeletionNotifierProtocol,
    ) -> None:
        self._transaction = transaction
        self._repository = repository
        self._notifier = notifier

    def read_ballot(
        self, *, sphere_id: SphereId, event_id: EventId, viewer_id: UserId
    ) -> EventDeletionBallotDTO:
        self._repository.read_event(
            sphere_id=sphere_id, event_id=event_id, for_update=False
        )
        managers = self._repository.manager_ids(sphere_id)
        approvals = self._counted_approvals(event_id=event_id, managers=managers)
        needed = approvals_needed(len(managers))
        missing = max(needed - len(approvals), 0)
        is_manager = viewer_id in managers
        has_approved = any(a.user_id == viewer_id for a in approvals)
        return EventDeletionBallotDTO(
            manager_count=len(managers),
            approvals_needed=needed,
            approvals=approvals,
            approvals_missing=missing,
            viewer_is_manager=is_manager,
            viewer_has_approved=has_approved,
            viewer_approval_deletes=is_manager and not has_approved and missing == 1,
            missing_after_viewer=max(missing - 1, 0),
        )

    def approve(
        self, *, sphere_id: SphereId, event_id: EventId, user_id: UserId
    ) -> EventDeletionOutcome:
        with self._transaction.atomic():
            # The row lock makes approvals queue up, so two managers approving
            # at once cannot both miss that together they reached the count.
            event = self._repository.read_event(
                sphere_id=sphere_id, event_id=event_id, for_update=True
            )
            managers = self._repository.manager_ids(sphere_id)
            if user_id not in managers:
                raise NotSphereManagerError
            self._repository.add_approval(event_id=event_id, user_id=user_id)
            approvals = self._counted_approvals(event_id=event_id, managers=managers)
            needed = approvals_needed(len(managers))
            if len(approvals) >= needed:
                self._repository.soft_delete_event(
                    event_id=event_id, at=datetime.now(tz=UTC)
                )
                logger.info(
                    "Event deleted: event=%s sphere=%s approvers=%s",
                    event_id,
                    sphere_id,
                    sorted(a.user_id for a in approvals),
                )
                return EventDeletionOutcome.DELETED
            logger.info(
                "Event deletion approved: event=%s sphere=%s user=%s approvals=%d/%d",
                event_id,
                sphere_id,
                user_id,
                len(approvals),
                needed,
            )
            if len(approvals) == 1:
                self._ask_the_others(
                    event=event,
                    requester_id=user_id,
                    managers=managers,
                    approvals_missing=needed - 1,
                )
            return EventDeletionOutcome.PENDING

    def withdraw(
        self, *, sphere_id: SphereId, event_id: EventId, user_id: UserId
    ) -> None:
        with self._transaction.atomic():
            self._repository.read_event(
                sphere_id=sphere_id, event_id=event_id, for_update=True
            )
            if user_id not in self._repository.manager_ids(sphere_id):
                raise NotSphereManagerError
            self._repository.remove_approval(event_id=event_id, user_id=user_id)
        logger.info(
            "Event deletion approval withdrawn: event=%s sphere=%s user=%s",
            event_id,
            sphere_id,
            user_id,
        )

    def _counted_approvals(
        self, *, event_id: EventId, managers: frozenset[UserId]
    ) -> list[EventDeletionApprovalDTO]:
        return [
            approval
            for approval in self._repository.list_approvals(event_id)
            if approval.user_id in managers
        ]

    def _ask_the_others(
        self,
        *,
        event: EventDeletionTargetDTO,
        requester_id: UserId,
        managers: frozenset[UserId],
        approvals_missing: int,
    ) -> None:
        requester_name = self._repository.user_name(requester_id)
        for manager_id in sorted(managers - {requester_id}):
            self._notifier.notify_event_deletion_requested(
                EventDeletionRequestedNotification(
                    recipient_user_id=manager_id,
                    requester_name=requester_name,
                    event_name=event.name,
                    event_slug=event.slug,
                    sphere_domain=event.sphere_domain,
                    approvals_missing=approvals_missing,
                )
            )
