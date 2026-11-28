from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING, assert_never

from ludamus.pacts.event_deletion import EventDeletionStep

if TYPE_CHECKING:
    from ludamus.pacts.ids import UserId

# Past this many approvals a large team is not made to chase everyone.
MAX_APPROVALS_NEEDED = 4
# Once a sphere has a second manager, no one deletes an event alone.
MIN_APPROVALS_NEEDED_IN_A_TEAM = 2


def approvals_needed(manager_count: int) -> int:
    """How many sphere managers must approve before an event is deleted.

    Half the managers, rounded up, capped at four; but two once there are two,
    so a solo manager acts alone and a pair must agree.
    """
    half = ceil(manager_count / 2)
    return min(
        manager_count,
        max(MIN_APPROVALS_NEEDED_IN_A_TEAM, min(half, MAX_APPROVALS_NEEDED)),
    )


@dataclass(frozen=True, slots=True)
class Ballot:
    """An event's deletion vote at one moment."""

    managers: frozenset[UserId]
    # Everyone with a stored approval, former managers included.
    approvers: frozenset[UserId]


@dataclass(frozen=True, slots=True)
class Refused:
    """Not a manager of the sphere: nothing is stored."""


@dataclass(frozen=True, slots=True)
class Recorded:
    """A new approval counts and more are missing."""

    missing: int


@dataclass(frozen=True, slots=True)
class AlreadyApproved:
    """This manager's approval is already counted: nothing changes."""

    missing: int


@dataclass(frozen=True, slots=True)
class Requested:
    """The first approval: it counts, and the other managers are asked."""

    missing: int
    recipients: frozenset[UserId]


@dataclass(frozen=True, slots=True)
class Deleted:
    """The approval completes the count: the event goes."""

    approvers: frozenset[UserId]

    @property
    def missing(self) -> int:
        return 0


type ApprovalDecision = Refused | AlreadyApproved | Recorded | Requested | Deleted


def decide_approval(ballot: Ballot, user_id: UserId) -> ApprovalDecision:
    """Decide what one manager's approval does to the vote.

    Only people who manage the sphere now are counted: someone who approved
    and then left the team no longer speaks for it.
    """
    if user_id not in ballot.managers:
        return Refused()
    before = ballot.managers.intersection(ballot.approvers)
    approving = before | {user_id}
    # Managers leaving after they approved can leave the count already met;
    # any manager's approval, even a repeated one, then completes it.
    if (missing := approvals_needed(len(ballot.managers)) - len(approving)) <= 0:
        return Deleted(approvers=approving)
    if user_id in before:
        return AlreadyApproved(missing=missing)
    if not before:
        return Requested(missing=missing, recipients=ballot.managers - {user_id})
    return Recorded(missing=missing)


def next_step(decision: ApprovalDecision) -> EventDeletionStep:
    """Name what pressing the button would do, from the decision it leads to."""
    match decision:
        case Refused():
            return EventDeletionStep.WATCH
        case Deleted():
            return EventDeletionStep.DELETE
        case Requested():
            return EventDeletionStep.REQUEST
        case Recorded():
            return EventDeletionStep.APPROVE
        case AlreadyApproved():
            return EventDeletionStep.WITHDRAW
        case _:
            assert_never(decision)
