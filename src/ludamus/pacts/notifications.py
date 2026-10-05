"""Contracts for the notification read path, subscriptions, and fanout.

The write side of per-user notifications belongs to the noun that raises it
— `pacts.enrollment` owns the promotion and offer notifications, `pacts.party`
the held-seat one. This module owns reading them back, the subscription model
(who follows which sphere, and mutes), and the announcement fanout
that turns one published announcement into many notification rows.
"""

from datetime import datetime
from enum import StrEnum, auto
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class SubscriptionSource(StrEnum):
    VISIT = auto()


class NotificationDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    kind: str
    title: str
    body: str
    url: str
    creation_time: datetime
    is_read: bool


class NavbarNotificationsDTO(BaseModel):
    unread_count: int
    items: list[NotificationDTO]


class NotificationReadRepositoryProtocol(Protocol):
    def unread_count(self, user_id: int) -> int: ...
    def total_count(self, user_id: int) -> int: ...
    def list_for_user(
        self, user_id: int, *, limit: int, offset: int = 0
    ) -> list[NotificationDTO]: ...
    def mark_read(self, user_id: int, pk: int) -> NotificationDTO | None: ...
    def mark_all_read(self, user_id: int) -> None: ...


class NotificationsServiceProtocol(Protocol):
    def get_navbar(self, user_id: int) -> NavbarNotificationsDTO: ...
    def total_count(self, user_id: int) -> int: ...
    def list_for_user(
        self, user_id: int, *, limit: int, offset: int = 0
    ) -> list[NotificationDTO]: ...
    def mark_read(self, user_id: int, pk: int) -> NotificationDTO | None: ...
    def mark_all_read(self, user_id: int) -> None: ...


class SubscriptionDTO(BaseModel):
    pk: int
    muted: bool
    sphere_name: str


class NotificationSubscriptionRepositoryProtocol(Protocol):
    # ensure_sphere creates a missing row only — an existing row keeps its
    # muted flag.
    def ensure_sphere(
        self, *, user_id: int, sphere_id: int, source: SubscriptionSource
    ) -> None: ...
    def list_for_user(self, user_id: int) -> list[SubscriptionDTO]: ...
    def set_muted(self, *, user_id: int, pk: int, muted: bool) -> bool: ...


class NotificationSubscriptionsServiceProtocol(Protocol):
    def subscribe_sphere_visit(self, *, user_id: int, sphere_id: int) -> None: ...
    def list_for_user(self, user_id: int) -> list[SubscriptionDTO]: ...

    # Raises NotFoundError when the subscription is not the user's.
    def set_muted(self, *, user_id: int, pk: int, muted: bool) -> None: ...


class ClaimedAnnouncementDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    sphere_id: int
    title: str
    content: str


class AnnouncementFanoutRepositoryProtocol(Protocol):
    # Atomically stamps notified_at on a published, not-yet-notified
    # announcement; None means someone else already claimed it (or it is not
    # published), so the caller must not fan out.
    def claim(self, announcement_id: int) -> ClaimedAnnouncementDTO | None: ...
    def due_ids(self) -> list[int]: ...
    def active_sphere_subscriber_ids(self, sphere_id: int) -> list[int]: ...
    def create_announcement_notifications(
        self, *, recipient_ids: list[int], announcement: ClaimedAnnouncementDTO
    ) -> int: ...


class AnnouncementFanoutServiceProtocol(Protocol):
    def fanout(self, announcement_id: int) -> int: ...
    def fanout_due(self) -> int: ...


class AnnouncementFanoutSchedulerProtocol(Protocol):
    def schedule_fanout(self, *, announcement_id: int) -> None: ...
