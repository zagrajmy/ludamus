from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.pacts.event_deletion import (
    EventDeletionBallotDTO,
    EventDeletionRequestedNotification,
    EventDeletionServiceProtocol,
    EventDeletionStep,
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


def _next_step(
    *, is_manager: bool, has_approved: bool, anyone_approved: bool, missing: int
) -> EventDeletionStep:
    if not is_manager:
        return EventDeletionStep.WATCH
    # Zero missing happens when managers leave after approving: the count is
    # met, and any manager's approval, even a repeated one, completes it.
    if missing == 0 or (missing == 1 and not has_approved):
        return EventDeletionStep.DELETE
    if has_approved:
        return EventDeletionStep.WITHDRAW
    return EventDeletionStep.APPROVE if anyone_approved else EventDeletionStep.REQUEST


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
        self._repository.read_event(sphere_id=sphere_id, event_id=event_id)
        managers = self._repository.manager_ids(sphere_id)
        approvals = self._counted_approvals(event_id=event_id, managers=managers)
        needed = approvals_needed(len(managers))
        missing = max(needed - len(approvals), 0)
        return EventDeletionBallotDTO(
            manager_count=len(managers),
            approvals_needed=needed,
            approvals=approvals,
            next_step=_next_step(
                is_manager=viewer_id in managers,
                has_approved=any(a.user_id == viewer_id for a in approvals),
                anyone_approved=bool(approvals),
                missing=missing,
            ),
            missing_after_viewer=max(missing - 1, 0),
        )

    def approve(
        self, *, sphere_id: SphereId, event_id: EventId, user_id: UserId
    ) -> int:
        with self._transaction.atomic():
            # The row lock makes approvals queue up, so two managers approving
            # at once cannot both miss that together they reached the count.
            event = self._repository.lock_event(sphere_id=sphere_id, event_id=event_id)
            managers = self._repository.manager_ids(sphere_id)
            if user_id not in managers:
                raise NotSphereManagerError
            added = self._repository.add_approval(event_id=event_id, user_id=user_id)
            approvals = self._counted_approvals(event_id=event_id, managers=managers)
            needed = approvals_needed(len(managers))
            missing = max(needed - len(approvals), 0)
            logger.info(
                "Event deletion approved: event=%s sphere=%s user=%s approvals=%d/%d",
                event_id,
                sphere_id,
                user_id,
                len(approvals),
                needed,
            )
            if missing == 0:
                self._repository.soft_delete_event(
                    event_id=event_id, at=datetime.now(tz=UTC)
                )
                logger.info(
                    "Event deleted: event=%s sphere=%s approvers=%s",
                    event_id,
                    sphere_id,
                    sorted(a.user_id for a in approvals),
                )
            # A repeated click by the same manager still checks the count
            # above, but the others were already asked when it was new.
            elif added and len(approvals) == 1:
                self._ask_the_others(
                    event=event,
                    requester=approvals[0],
                    managers=managers,
                    approvals_missing=missing,
                )
            return missing

    def withdraw(
        self, *, sphere_id: SphereId, event_id: EventId, user_id: UserId
    ) -> None:
        with self._transaction.atomic():
            self._repository.lock_event(sphere_id=sphere_id, event_id=event_id)
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
        requester: EventDeletionApprovalDTO,
        managers: frozenset[UserId],
        approvals_missing: int,
    ) -> None:
        for manager_id in sorted(managers - {requester.user_id}):
            self._notifier.notify_event_deletion_requested(
                EventDeletionRequestedNotification(
                    recipient_user_id=manager_id,
                    requester_name=requester.user_name,
                    event_name=event.name,
                    event_slug=event.slug,
                    sphere_domain=event.sphere_domain,
                    approvals_missing=approvals_missing,
                )
            )
