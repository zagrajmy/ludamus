from __future__ import annotations

from datetime import datetime
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from ludamus.pacts.ids import EventId, SphereId, UserId


class NotSphereManagerError(Exception):
    """Only a sphere manager may approve or withdraw an event's deletion."""


class EventDeletionStep(StrEnum):
    """What the viewer of an event's deletion vote can do next."""

    # Not a sphere manager: they see the count and nothing to press.
    WATCH = auto()
    # No one has approved yet: approving asks the other managers.
    REQUEST = auto()
    # Others approved, and more are needed after the viewer.
    APPROVE = auto()
    # The viewer's approval is the last one missing.
    DELETE = auto()
    # The viewer approved and waits for the others.
    WITHDRAW = auto()


class EventDeletionApprovalDTO(BaseModel):
    user_id: int
    user_name: str
    approved_at: datetime


class EventDeletionBallotDTO(BaseModel):
    """Where an event's deletion vote stands, as one viewer sees it."""

    manager_count: int
    approvals_needed: int
    approvals: list[EventDeletionApprovalDTO]
    next_step: EventDeletionStep
    # How many approvals would still be missing after the viewer's own.
    missing_after_viewer: int


class EventDeletionTargetDTO(BaseModel):
    pk: int
    name: str
    slug: str
    sphere_domain: str


class EventDeletionRequestedNotification(BaseModel):
    recipient_user_id: int
    requester_name: str
    event_name: str
    event_slug: str
    sphere_domain: str
    approvals_missing: int


class EventDeletionRepositoryProtocol(Protocol):
    @staticmethod
    def read_event(*, sphere_id: SphereId, event_id: EventId) -> EventDeletionTargetDTO:
        """Read the sphere's live event.

        Raises:
            NotFoundError: the sphere has no live event with this id.
        """

    @staticmethod
    def lock_event(*, sphere_id: SphereId, event_id: EventId) -> EventDeletionTargetDTO:
        """Read the sphere's live event and hold its row until commit.

        Raises:
            NotFoundError: the sphere has no live event with this id.
        """

    @staticmethod
    def manager_ids(sphere_id: SphereId) -> frozenset[UserId]: ...
    @staticmethod
    def list_approvals(event_id: EventId) -> list[EventDeletionApprovalDTO]: ...
    @staticmethod
    def add_approval(*, event_id: EventId, user_id: UserId) -> EventDeletionApprovalDTO:
        """Record the approval, or return the one this manager already has."""

    @staticmethod
    def remove_approval(*, event_id: EventId, user_id: UserId) -> None: ...
    @staticmethod
    def soft_delete_event(*, event_id: EventId, at: datetime) -> None:
        """Hide the event and its live sessions, stamped with the same time.

        The shared stamp is what restoring keys on: sessions deleted before
        the event keep their own, older time and stay deleted.
        """


class EventDeletionNotifierProtocol(Protocol):
    def notify_event_deletion_requested(
        self, notification: EventDeletionRequestedNotification
    ) -> None: ...


class EventDeletionServiceProtocol(Protocol):
    def read_ballot(
        self, *, sphere_id: SphereId, event_id: EventId, viewer_id: UserId
    ) -> EventDeletionBallotDTO: ...
    def approve(
        self, *, sphere_id: SphereId, event_id: EventId, user_id: UserId
    ) -> int:
        """Record the manager's approval; delete the event if it was the last.

        Returns:
            How many approvals are still missing; 0 means the event is deleted.
        """

    def withdraw(
        self, *, sphere_id: SphereId, event_id: EventId, user_id: UserId
    ) -> None: ...
