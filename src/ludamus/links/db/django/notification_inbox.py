"""The bell's own reads: what a user has been told, and marking it read."""

from datetime import UTC, datetime

from ludamus.links.db.django.models import Notification
from ludamus.pacts.notifications import NotificationDTO


class NotificationReadRepository:
    @staticmethod
    def unread_count(user_id: int) -> int:
        return Notification.objects.filter(
            recipient_id=user_id, read_at__isnull=True
        ).count()

    @staticmethod
    def total_count(user_id: int) -> int:
        return Notification.objects.filter(recipient_id=user_id).count()

    @staticmethod
    def list_for_user(
        user_id: int, *, limit: int, offset: int = 0
    ) -> list[NotificationDTO]:
        # The window is the query's, not Python's: the bell asks for the first
        # ten and the history page for one page, so a long backlog is never
        # loaded whole to show a screenful.
        # `-pk` only breaks ties: two notifications raised in the same
        # transaction share a timestamp, and a page window needs a total order
        # or rows drift between pages.
        rows = Notification.objects.filter(recipient_id=user_id).order_by(
            "-creation_time", "-pk"
        )[offset : offset + limit]
        return [NotificationDTO.model_validate(notification) for notification in rows]

    @staticmethod
    def mark_read(user_id: int, pk: int) -> NotificationDTO | None:
        # Scoped by recipient AND pk: a notification addressed to someone else
        # returns None (the view 404s) and is never mutated.
        notification = Notification.objects.filter(recipient_id=user_id, pk=pk).first()
        if notification is None:
            return None
        if notification.read_at is None:
            notification.read_at = datetime.now(UTC)
            notification.save(update_fields=["read_at"])
        return NotificationDTO.model_validate(notification)

    @staticmethod
    def mark_all_read(user_id: int) -> None:
        Notification.objects.filter(recipient_id=user_id, read_at__isnull=True).update(
            read_at=datetime.now(UTC)
        )
