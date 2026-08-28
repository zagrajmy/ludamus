"""User notifier: persists in-app Notification rows and sends email.

Implements `UserNotifierProtocol` behind which the promotion mill sits, so the
mill never touches Django mail/ORM directly. Composes localised (PL/EN) copy at
send time and links each notification to the relevant page.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.timezone import localtime
from django.utils.translation import gettext as _

from ludamus.links.db.django.models import Notification, Session
from ludamus.pacts.legacy import NotificationKind
from ludamus.pacts.notifications import NotificationDTO

if TYPE_CHECKING:
    from ludamus.pacts.crowd import (
        EmailChangeCompletedNotification,
        EmailChangeRequestedNotification,
        EmailVerificationNotification,
    )
    from ludamus.pacts.enrollment import OfferNotification, PromotionNotification
    from ludamus.pacts.party import (
        HeldSeatNotification,
        PartyEnrolledNotification,
        PartyInviteNotification,
    )
    from ludamus.pacts.printing import PrintablesReadyNotification
    from ludamus.pacts.safety import ShadowbanSignupNotification


logger = logging.getLogger(__name__)


def _absolute(path: str, *, domain: str) -> str:
    scheme = "http" if "localhost" in domain else "https"
    return f"{scheme}://{domain}{path}"


def _session_enrollment_url(event_slug: str, session_id: int) -> str:
    return _absolute(
        reverse(
            "web:chronology:session-enrollment",
            kwargs={"event_slug": event_slug, "session_id": session_id},
        ),
        domain=_session_host(session_id),
    )


def _session_host(session_id: int) -> str:
    domain = (
        Session.objects.filter(pk=session_id)
        .values_list("event__sphere__site__domain", flat=True)
        .first()
    )
    if not domain:
        logger.warning(
            "No sphere host for session %s; linking to %s",
            session_id,
            settings.ROOT_DOMAIN,
        )
        return str(settings.ROOT_DOMAIN)
    return domain


class DjangoUserNotifier:
    def notify_promoted(self, notification: PromotionNotification) -> None:
        url = _session_enrollment_url(notification.event_slug, notification.session_id)
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
        url = _absolute(
            reverse(
                "web:chronology:offer-claim", kwargs={"token": notification.claim_token}
            ),
            domain=_session_host(notification.session_id),
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
        # Flow-neutral: an expired row may be a waitlist offer or a seat a
        # leader held — nothing on it records which, so the copy fits both.
        title = _("Your offer for %(session)s expired") % {
            "session": notification.session_title
        }
        body = _(
            "The seat was not claimed in time and has been released. You can "
            "sign up again if you are still interested."
        )
        self._deliver(
            Notification(
                recipient_id=notification.recipient_user_id,
                kind=NotificationKind.OFFER_EXPIRED.value,
                title=title,
                body=body,
                url=_session_enrollment_url(
                    notification.event_slug, notification.session_id
                ),
                payload={"session_id": notification.session_id},
            ),
            notification.recipient_email,
        )

    def notify_party_invited(self, notification: PartyInviteNotification) -> None:
        party = notification.party_name or _("their party")
        title = _("%(member)s invited you to %(party)s") % {
            "member": notification.actor_name,
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
                url=_absolute(
                    reverse("web:crowd:profile-parties"), domain=settings.ROOT_DOMAIN
                ),
                payload={},
            ),
            notification.recipient_email,
        )

    def notify_party_enrolled(self, notification: PartyEnrolledNotification) -> None:
        url = _session_enrollment_url(notification.event_slug, notification.session_id)
        title = _("%(leader)s enrolled you in %(session)s") % {
            "leader": notification.actor_name,
            "session": notification.session_title,
        }
        body = _(
            "You have a confirmed spot. If it does not fit your plans, you "
            "can cancel on the session page."
        )
        self._deliver(
            Notification(
                recipient_id=notification.recipient_user_id,
                kind=NotificationKind.PARTY_ENROLLED.value,
                title=title,
                body=body,
                url=url,
                payload={"session_id": notification.session_id},
            ),
            notification.recipient_email,
        )

    def notify_seat_held(self, notification: HeldSeatNotification) -> None:
        url = _absolute(
            reverse(
                "web:chronology:offer-claim", kwargs={"token": notification.claim_token}
            ),
            domain=_session_host(notification.session_id),
        )
        deadline = date_format(
            localtime(notification.offer_expires_at), "DATETIME_FORMAT"
        )
        title = _("%(leader)s saved you a seat in %(session)s") % {
            "leader": notification.actor_name,
            "session": notification.session_title,
        }
        body = _(
            "The seat is yours once you claim it — do so before %(deadline)s "
            "or it will be released."
        ) % {"deadline": deadline}
        self._deliver(
            Notification(
                recipient_id=notification.recipient_user_id,
                kind=NotificationKind.PARTY_SEAT_HELD.value,
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

    def notify_email_verification(
        self, notification: EmailVerificationNotification
    ) -> None:
        url = _absolute(
            reverse("web:crowd:email-confirm", kwargs={"token": notification.token}),
            domain=settings.ROOT_DOMAIN,
        )
        title = _("Confirm your email address")
        body = _(
            "Use the link below to confirm this address for your account. "
            "The link is valid for 24 hours."
        )
        self._deliver(
            Notification(
                recipient_id=notification.recipient_user_id,
                kind=NotificationKind.EMAIL_VERIFICATION.value,
                title=title,
                body=body,
                url=url,
                payload={},
            ),
            notification.recipient_email,
        )

    def notify_email_change_requested(
        self, notification: EmailChangeRequestedNotification
    ) -> None:
        url = _absolute(
            reverse(
                "web:crowd:email-cancel", kwargs={"token": notification.cancel_token}
            ),
            domain=settings.ROOT_DOMAIN,
        )
        title = _("Your email address is being changed")
        body = _(
            "Someone asked to change your account's email address to "
            "%(new_address)s. If that was not you, cancel the change with the "
            "link below within 24 hours."
        ) % {"new_address": notification.new_address}
        self._deliver(
            Notification(
                recipient_id=notification.recipient_user_id,
                kind=NotificationKind.EMAIL_CHANGE_REQUESTED.value,
                title=title,
                body=body,
                url=url,
                payload={"new_address": notification.new_address},
            ),
            notification.recipient_email,
        )

    def notify_email_change_completed(
        self, notification: EmailChangeCompletedNotification
    ) -> None:
        title = _("Your email address was changed")
        body = _(
            "Your account's email address is now %(new_address)s. Sign-in and "
            "notifications use the new address from now on."
        ) % {"new_address": notification.new_address}
        self._deliver(
            Notification(
                recipient_id=notification.recipient_user_id,
                kind=NotificationKind.EMAIL_CHANGE_COMPLETED.value,
                title=title,
                body=body,
                url=_absolute(
                    reverse("web:crowd:profile"), domain=settings.ROOT_DOMAIN
                ),
                payload={"new_address": notification.new_address},
            ),
            notification.recipient_email,
        )

    def notify_printables_ready(
        self, notification: PrintablesReadyNotification
    ) -> None:
        url = _absolute(
            reverse(
                "web:chronology:event-print", kwargs={"slug": notification.event_slug}
            ),
            domain=notification.sphere_domain,
        )
        title = _("Print your materials for %(event)s") % {
            "event": notification.event_name
        }
        body = _(
            "%(event)s starts in two days. Print the timetable and door cards "
            "for your event using the link below before it begins."
        ) % {"event": notification.event_name}
        self._deliver(
            Notification(
                recipient_id=notification.recipient_user_id,
                kind=NotificationKind.PRINTABLES_READY.value,
                title=title,
                body=body,
                url=url,
                payload={"event_slug": notification.event_slug},
            ),
            notification.recipient_email,
        )

    def notify_shadowbanned_signup(
        self, notification: ShadowbanSignupNotification
    ) -> None:
        title = (
            _("A shadowbanned player joined %(session)s with you")
            % {"session": notification.session_title}
            if notification.session_player_names
            else _("A shadowbanned player joined %(event)s")
            % {"event": notification.event_name}
        )
        parts = []
        if notification.session_player_names:
            parts.append(
                _(
                    "Someone you shadowbanned signed up to %(session)s, "
                    "where you are playing: %(players)s."
                )
                % {
                    "session": notification.session_title,
                    "players": ", ".join(notification.session_player_names),
                }
            )
        if notification.player_names:
            parts.append(
                _("Someone you shadowbanned signed up to %(event)s: %(players)s.")
                % {
                    "event": notification.event_name,
                    "players": ", ".join(notification.player_names),
                }
            )
        parts.append(_("They have not been notified. Review the event if you need to."))
        body = " ".join(parts)
        self._deliver(
            Notification(
                recipient_id=notification.recipient_user_id,
                kind=NotificationKind.SHADOWBANNED_SIGNUP.value,
                title=title,
                body=body,
                url=_absolute(
                    reverse(
                        "web:chronology:event", kwargs={"slug": notification.event_slug}
                    ),
                    domain=notification.sphere_domain,
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
            # Blank means no address or an unverified one (the caller resolves
            # the deliverable address) — the bell row above still lands.
            logger.info(
                "No deliverable address for notification kind=%s recipient=%s",
                notification.kind,
                notification.recipient_id,
            )
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
