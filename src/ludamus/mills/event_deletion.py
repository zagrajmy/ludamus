from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, assert_never

from ludamus.pacts.event_deletion import (
    EventDeletionBallotDTO,
    EventDeletionRequestedNotification,
    EventDeletionServiceProtocol,
    NotSphereManagerError,
)
from ludamus.pacts.ids import UserId
from ludamus.specs.event_deletion import (
    AlreadyApproved,
    Ballot,
    Deleted,
    Recorded,
    Refused,
    Requested,
    approvals_needed,
    decide_approval,
    next_step,
)

if TYPE_CHECKING:
    from ludamus.pacts.event_deletion import (
        EventDeletionApprovalDTO,
        EventDeletionNotifierProtocol,
        EventDeletionRepositoryProtocol,
        EventDeletionTargetDTO,
    )
    from ludamus.pacts.ids import EventId, SphereId
    from ludamus.pacts.services import TransactionProtocol

logger = logging.getLogger(__name__)


def _ballot(
    managers: frozenset[UserId], stored: list[EventDeletionApprovalDTO]
) -> Ballot:
    return Ballot(
        managers=managers, approvers=frozenset(UserId(a.user_id) for a in stored)
    )


class EventDeletionService(EventDeletionServiceProtocol):
    """Deletes an event once enough of its sphere's managers approve.

    The rules are `decide_approval` in specs. A method here reads the vote,
    asks for the decision and writes what it says.
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
        stored = self._repository.list_approvals(event_id)
        decision = decide_approval(_ballot(managers, stored), viewer_id)
        return EventDeletionBallotDTO(
            manager_count=len(managers),
            approvals_needed=approvals_needed(len(managers)),
            approvals=[a for a in stored if a.user_id in managers],
            next_step=next_step(decision),
            missing_after_viewer=(
                0 if isinstance(decision, Refused) else decision.missing
            ),
        )

    def approve(
        self, *, sphere_id: SphereId, event_id: EventId, user_id: UserId
    ) -> int:
        with self._transaction.atomic():
            # The row lock makes approvals queue up, so two managers approving
            # at once cannot both miss that together they reached the count.
            event = self._repository.lock_event(sphere_id=sphere_id, event_id=event_id)
            managers = self._repository.manager_ids(sphere_id)
            decision = decide_approval(
                _ballot(managers, self._repository.list_approvals(event_id)), user_id
            )
            if isinstance(decision, Refused):
                raise NotSphereManagerError
            approval = self._repository.add_approval(event_id=event_id, user_id=user_id)
            match decision:
                case AlreadyApproved() | Recorded():
                    pass
                case Requested(missing=missing, recipients=recipients):
                    self._ask(
                        event=event,
                        requester_name=approval.user_name,
                        recipients=recipients,
                        approvals_missing=missing,
                    )
                case Deleted(approvers=approvers):
                    self._repository.soft_delete_event(
                        event_id=event_id, at=datetime.now(tz=UTC)
                    )
                    logger.info(
                        "Event deleted: event=%s sphere=%s approvers=%s",
                        event_id,
                        sphere_id,
                        sorted(approvers),
                    )
                case _:
                    assert_never(decision)
            logger.info(
                "Event deletion approved: event=%s sphere=%s user=%s missing=%d",
                event_id,
                sphere_id,
                user_id,
                decision.missing,
            )
            return decision.missing

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

    def _ask(
        self,
        *,
        event: EventDeletionTargetDTO,
        requester_name: str,
        recipients: frozenset[UserId],
        approvals_missing: int,
    ) -> None:
        for manager_id in sorted(recipients):
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
