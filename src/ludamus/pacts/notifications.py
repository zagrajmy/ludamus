"""Contracts for the notification read path: the navbar bell and its history.

The write side (what raises a notification) belongs to the noun that raises it
— `pacts.enrollment` owns the promotion and offer notifications, `pacts.party`
the held-seat one. This module is only about reading them back and marking
them read.
"""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict


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
