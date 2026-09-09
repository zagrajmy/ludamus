"""Read path for notifications: the navbar bell, the history page, mark-as-read."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.pacts.notifications import (
    NavbarNotificationsDTO,
    NotificationsServiceProtocol,
)

if TYPE_CHECKING:
    from ludamus.pacts.notifications import (
        NotificationDTO,
        NotificationReadRepositoryProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol

NAVBAR_LIMIT = 10


class NotificationsService(NotificationsServiceProtocol):
    def __init__(
        self,
        transaction: TransactionProtocol,
        notifications: NotificationReadRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._notifications = notifications

    def get_navbar(self, user_id: int) -> NavbarNotificationsDTO:
        return NavbarNotificationsDTO(
            unread_count=self._notifications.unread_count(user_id),
            items=self._notifications.list_for_user(user_id, limit=NAVBAR_LIMIT),
        )

    def total_count(self, user_id: int) -> int:
        return self._notifications.total_count(user_id)

    def list_for_user(
        self, user_id: int, *, limit: int, offset: int = 0
    ) -> list[NotificationDTO]:
        return self._notifications.list_for_user(user_id, limit=limit, offset=offset)

    def mark_read(self, user_id: int, pk: int) -> NotificationDTO | None:
        with self._transaction.atomic():
            return self._notifications.mark_read(user_id, pk)

    def mark_all_read(self, user_id: int) -> None:
        with self._transaction.atomic():
            self._notifications.mark_all_read(user_id)
