"""User notifier: persists in-app Notification rows and sends email.

Implements `UserNotifierProtocol` behind which the promotion mill sits, so the
mill never touches Django mail/ORM directly. Composes localised (PL/EN) copy at
send time and links each notification to the relevant page.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.timezone import localtime
from django.utils.translation import gettext as _

from ludamus.adapters.db.django.models import Notification
from ludamus.pacts.enrollment import NotificationDTO
from ludamus.pacts.legacy import NotificationKind

if TYPE_CHECKING:
    from ludamus.pacts.enrollment import OfferNotification, PromotionNotification
    from ludamus.pacts.party import PartyInviteNotification
    from ludamus.pacts.safety import ShadowbanSignupNotification


class DjangoUserNotifier:
    def notify_promoted(self, notification: PromotionNotification) -> None:
        url = reverse(
            "web:chronology:session-enrollment",
            kwargs={
                "event_slug": notification.event_slug,
                "session_id": notification.session_id,
            },
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
                    kwargs={
                        "event_slug": notification.event_slug,
                        "session_id": notification.session_id,
                    },
                ),
                payload={"session_id": notification.session_id},
            ),
            notification.recipient_email,
        )

    def notify_party_invited(self, notification: PartyInviteNotification) -> None:
        party = notification.party_name or _("their party")
        title = _("%(leader)s invited you to %(party)s") % {
            "leader": notification.leader_name,
            "party": party,
        }
        body = _(
            "Join the party to enroll in events together — you move up "
            "waiting lists as one group. You decide about every enrollment "
            "unless you say otherwise."
        )
        self._deliver(
            Notification(
                recipient_id=notification.recipient_user_id,
                kind=NotificationKind.PARTY_INVITE.value,
                title=title,
                body=body,
                url=reverse("web:crowd:profile-parties"),
                payload={},
            ),
            notification.recipient_email,
        )

    def notify_shadowbanned_signup(
        self, notification: ShadowbanSignupNotification
    ) -> None:
        players = ", ".join(notification.player_names)
        title = _("A shadowbanned player joined %(event)s") % {
            "event": notification.event_name
        }
        body = _(
            "Someone you shadowbanned signed up to %(event)s: %(players)s. "
            "They have not been notified. Review the event if you need to."
        ) % {"event": notification.event_name, "players": players}
        self._deliver(
            Notification(
                recipient_id=notification.recipient_user_id,
                kind=NotificationKind.SHADOWBANNED_SIGNUP.value,
                title=title,
                body=body,
                url=reverse(
                    "web:chronology:event", kwargs={"slug": notification.event_slug}
                ),
                payload={"event_slug": notification.event_slug},
            ),
            notification.recipient_email,
        )

    @staticmethod
    def _deliver(notification: Notification, email: str) -> None:
        # Persist the row inside the surrounding transaction so a rolled-back
        # promotion drops its notification too (the row is consistent with the
        # seat change it announces). Only the email is deferred to after-commit,
        # best-effort: SMTP can't be un-sent, so it must wait for the real commit
        # and must not roll back a confirmed seat if it fails.
        notification.save()
        if not email:
            return

        def _send_email() -> None:
            send_mail(
                subject=notification.title,
                message=f"{notification.body}\n\n{notification.url}",
                from_email=None,
                recipient_list=[email],
                fail_silently=True,
            )

        transaction.on_commit(_send_email)


class NotificationReadRepository:
    @staticmethod
    def unread_count(user_id: int) -> int:
        return Notification.objects.filter(
            recipient_id=user_id, read_at__isnull=True
        ).count()

    @staticmethod
    def list_recent(user_id: int, limit: int) -> list[NotificationDTO]:
        recent = Notification.objects.filter(recipient_id=user_id).order_by(
            "-creation_time"
        )[:limit]
        return [NotificationDTO.model_validate(notification) for notification in recent]

    @staticmethod
    def mark_all_read(user_id: int) -> None:
        Notification.objects.filter(recipient_id=user_id, read_at__isnull=True).update(
            read_at=datetime.now(UTC)
        )
