"""User notifier: persists in-app Notification rows and sends email.

Implements `UserNotifierProtocol` behind which the promotion mill sits, so the
mill never touches Django mail/ORM directly. Composes localised (PL/EN) copy at
send time and links each notification to the relevant page.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.core.mail import send_mail
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.timezone import localtime
from django.utils.translation import gettext as _

from ludamus.adapters.db.django.models import Notification
from ludamus.pacts.enrollment import NotificationDTO
from ludamus.pacts.legacy import NotificationKind

if TYPE_CHECKING:
    from ludamus.pacts.enrollment import OfferNotification, PromotionNotification


class DjangoUserNotifier:
    def notify_promoted(self, notification: PromotionNotification) -> None:
        url = reverse(
            "web:chronology:session-enrollment",
            kwargs={"session_id": notification.session_id},
        )
        title = _("You're in: a spot opened in %(session)s") % {
            "session": notification.session_title
        }
        body = _("A confirmed spot opened up and you have been enrolled automatically.")
        self._deliver(
            Notification(
                recipient_id=notification.recipient_user_id,
                kind=NotificationKind.WAITLIST_PROMOTED.value,
                title=title,
                body=body,
                url=url,
                payload={"session_id": notification.session_id},
            ),
            notification.recipient_email,
        )

    def notify_offered(self, notification: OfferNotification) -> None:
        url = reverse(
            "web:chronology:offer-claim", kwargs={"token": notification.claim_token}
        )
        deadline = date_format(
            localtime(notification.offer_expires_at), "DATETIME_FORMAT"
        )
        title = _("A spot opened in %(session)s — claim it by %(deadline)s") % {
            "session": notification.session_title,
            "deadline": deadline,
        }
        body = _(
            "A spot opened up — claim it before %(deadline)s using the link "
            "below, or it will go to the next person on the waiting list."
        ) % {"deadline": deadline}
        self._deliver(
            Notification(
                recipient_id=notification.recipient_user_id,
                kind=NotificationKind.WAITLIST_OFFER.value,
                title=title,
                body=body,
                url=url,
                payload={
                    "session_id": notification.session_id,
                    "claim_token": notification.claim_token,
                    "offer_expires_at": notification.offer_expires_at.isoformat(),
                },
            ),
            notification.recipient_email,
        )

    def notify_offer_expired(self, notification: PromotionNotification) -> None:
        title = _("Your offer for %(session)s expired") % {
            "session": notification.session_title
        }
        body = _(
            "Your offered spot was not claimed in time and has gone to the next "
            "person. You can join the waiting list again if you are still "
            "interested."
        )
        self._deliver(
            Notification(
                recipient_id=notification.recipient_user_id,
                kind=NotificationKind.OFFER_EXPIRED.value,
                title=title,
                body=body,
                url=reverse(
                    "web:chronology:session-enrollment",
                    kwargs={"session_id": notification.session_id},
                ),
                payload={"session_id": notification.session_id},
            ),
            notification.recipient_email,
        )

    @staticmethod
    def _deliver(notification: Notification, email: str) -> None:
        notification.save()
        if email:
            send_mail(
                subject=notification.title,
                message=f"{notification.body}\n\n{notification.url}",
                from_email=None,
                recipient_list=[email],
                fail_silently=False,
            )


class NotificationReadRepository:
    @staticmethod
    def unread_count(user_id: int) -> int:
        return Notification.objects.filter(
            recipient_id=user_id, read_at__isnull=True
        ).count()

    @staticmethod
    def list_recent(user_id: int, limit: int) -> list[NotificationDTO]:
        recent = Notification.objects.filter(recipient_id=user_id)[:limit]
        return [NotificationDTO.model_validate(notification) for notification in recent]

    @staticmethod
    def mark_all_read(user_id: int) -> None:
        Notification.objects.filter(
            recipient_id=user_id, read_at__isnull=True
        ).update(read_at=datetime.now(UTC))
