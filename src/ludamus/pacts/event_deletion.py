from __future__ import annotations

from datetime import datetime
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from ludamus.pacts.ids import EventId, SphereId, UserId


class NotSphereManagerError(Exception):
    """Only a sphere manager may approve or withdraw an event's deletion."""


class EventDeletionApprovalDTO(BaseModel):
    user_id: int
    user_name: str
    approved_at: datetime


class EventDeletionBallotDTO(BaseModel):
    """Where an event's deletion vote stands, as one viewer sees it."""

    manager_count: int
    approvals_needed: int
    approvals: list[EventDeletionApprovalDTO]
    approvals_missing: int
    viewer_is_manager: bool
    viewer_has_approved: bool
    # The viewer's approval is the last one missing: it deletes the event.
    viewer_approval_deletes: bool
    # How many approvals would still be missing after the viewer's own.
    missing_after_viewer: int


class EventDeletionOutcome(StrEnum):
    DELETED = auto()
    PENDING = auto()


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
    def read_event(
        *, sphere_id: SphereId, event_id: EventId, for_update: bool
    ) -> EventDeletionTargetDTO:
        """Read the sphere's live event; `for_update` holds its row until commit.

        Raises:
            NotFoundError: the sphere has no live event with this id.
        """

    @staticmethod
    def manager_ids(sphere_id: SphereId) -> frozenset[UserId]: ...
    @staticmethod
    def user_name(user_id: UserId) -> str: ...
    @staticmethod
    def list_approvals(event_id: EventId) -> list[EventDeletionApprovalDTO]: ...
    @staticmethod
    def add_approval(*, event_id: EventId, user_id: UserId) -> None: ...
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
    ) -> EventDeletionOutcome: ...
    def withdraw(
        self, *, sphere_id: SphereId, event_id: EventId, user_id: UserId
    ) -> None: ...
