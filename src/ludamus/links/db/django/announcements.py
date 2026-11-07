"""Announcement fan-out: one organizer's words to every subscriber's bell."""

from __future__ import annotations

from datetime import UTC, datetime

from ludamus.links.db.django.delivery import ring_as_written
from ludamus.links.db.django.models import Announcement, NotificationSubscription
from ludamus.pacts.legacy import NotificationKind
from ludamus.pacts.notifications import ClaimedAnnouncementDTO


class AnnouncementFanoutRepository:
    @staticmethod
    def claim(announcement_id: int) -> ClaimedAnnouncementDTO | None:
        # The filtered UPDATE is the notify-at-most-once gate: only one caller
        # ever flips notified_at from NULL, everyone else gets 0 rows and backs
        # off. Republishing keeps the stamp, so it never re-notifies.
        updated = Announcement.objects.filter(
            pk=announcement_id, is_published=True, notified_at__isnull=True
        ).update(notified_at=datetime.now(UTC))
        if not updated:
            return None
        return ClaimedAnnouncementDTO.model_validate(
            Announcement.objects.get(pk=announcement_id)
        )

    @staticmethod
    def due_ids() -> list[int]:
        return list(
            Announcement.objects.filter(
                is_published=True, notified_at__isnull=True
            ).values_list("pk", flat=True)
        )

    @staticmethod
    def active_sphere_subscriber_ids(sphere_id: int) -> list[int]:
        return list(
            NotificationSubscription.objects.filter(
                sphere_id=sphere_id, muted=False
            ).values_list("user_id", flat=True)
        )

    @staticmethod
    def create_announcement_notifications(
        *, recipient_ids: list[int], announcement: ClaimedAnnouncementDTO
    ) -> int:
        # Empty url routes the bell to the in-place overlay — an announcement
        # is read where you are, it does not navigate.
        return ring_as_written(
            recipient_ids=recipient_ids,
            kind=NotificationKind.ANNOUNCEMENT,
            title=announcement.title,
            body=announcement.content,
            url="",
            payload={"announcement_id": announcement.pk},
        )
