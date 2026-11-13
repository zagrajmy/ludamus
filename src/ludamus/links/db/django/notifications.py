"""User notifier: persists in-app Notification rows and sends email.

Implements `UserNotifierProtocol` behind which the promotion mill sits, so the
mill never touches Django mail/ORM directly. Composes localised (PL/EN) copy at
send time, in the recipient's language, and links each notification to the
relevant page.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import transaction
from django.db.models.functions import Lower
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.text import Truncator
from django.utils.timezone import localtime
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from ludamus.links.absolute_url import absolute_url
from ludamus.links.db.django.delivery import Bell, compose_mail, ring, send
from ludamus.links.db.django.models import (
    NOTIFICATION_TITLE_MAX_LENGTH,
    NotificationSubscription,
    Session,
    SphereSubscription,
)
from ludamus.links.db.django.notification_inbox import already_told
from ludamus.links.db.django.recipients import Voice, speaking_to
from ludamus.links.db.django.session_urls import session_popup_url
from ludamus.pacts.notifications import NotificationKind, SubscriptionDTO
from ludamus.pacts.user import EMAIL_LINK_MAX_AGE, AgeBand

if TYPE_CHECKING:
    from ludamus.links.db.django.recipients import Recipient
    from ludamus.pacts.dashboard import SphereEventPublishedNotification
    from ludamus.pacts.enrollment import OfferNotification, PromotionNotification
    from ludamus.pacts.listing import (
        ListingDeclinedNotification,
        ListingInterestedNotification,
        ListingNotification,
    )
    from ludamus.pacts.notifications import SubscriptionSource
    from ludamus.pacts.party import (
        HeldSeatNotification,
        PartyEnrolledNotification,
        PartyInviteNotification,
    )
    from ludamus.pacts.printing import PrintablesReadyNotification
    from ludamus.pacts.safety import ShadowbanSignupNotification
    from ludamus.pacts.sessions import (
        AnonymousProposalAcceptedNotification,
        ProposalAcceptance,
        ProposalAcceptedNotification,
    )
    from ludamus.pacts.user import (
        EmailChangeCompletedNotification,
        EmailChangeRequestedNotification,
        EmailVerificationNotification,
    )


logger = logging.getLogger(__name__)

_EMAIL_LINK_HOURS = EMAIL_LINK_MAX_AGE // timedelta(hours=1)


def _session_url(event_slug: str, session_id: int) -> str:
    return session_popup_url(
        event_slug=event_slug, session_id=session_id, domain=_session_host(session_id)
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


def _acceptance_copy(acceptance: ProposalAcceptance) -> tuple[str, str, str]:
    if acceptance.placed:
        url = _session_url(acceptance.event_slug, acceptance.session_id)
        body = _(
            "Your proposal for %(event)s was accepted and added to the agenda."
        ) % {"event": acceptance.event_name}
    else:
        url = absolute_url(
            reverse("web:chronology:event", kwargs={"slug": acceptance.event_slug}),
            domain=_session_host(acceptance.session_id),
        )
        body = _(
            "Your proposal for %(event)s was accepted. It will appear on the "
            "agenda once the organizers give it a time and place."
        ) % {"event": acceptance.event_name}
    title = Truncator(
        _("Accepted: %(session)s") % {"session": acceptance.session_title}
    ).chars(NOTIFICATION_TITLE_MAX_LENGTH)
    return title, body, url


def _ring_board(
    notification: ListingNotification,
    *,
    recipient: Recipient,
    kind: NotificationKind,
    title: str,
    body: str,
    url_name: str = "web:board:detail",
) -> None:
    # Board notices land in the bell only; no mail goes out for them.
    ring(
        recipient,
        Bell(
            kind=kind,
            title=Truncator(title).chars(NOTIFICATION_TITLE_MAX_LENGTH),
            body=body,
            url=absolute_url(
                reverse(url_name, kwargs={"pk": notification.listing_id}),
                domain=str(settings.ROOT_DOMAIN),
            ),
            payload={"listing_id": notification.listing_id},
        ),
    )


def _deliver(recipient: Recipient, bell: Bell) -> None:
    # Persist the row inside the surrounding transaction so a rolled-back
    # promotion drops its notification too (the row is consistent with the
    # seat change it announces). Only the email is deferred to after-commit,
    # best-effort: SMTP can't be un-sent, so it must wait for the real commit
    # and must not roll back a confirmed seat if it fails.
    ring(recipient, bell)
    if not recipient.can_mail:
        # No address, or none anyone proved — the bell row above still
        # lands, so an unproven address costs a mail, not a notification.
        logger.info(
            "No deliverable address for notification kind=%s recipient=%s",
            bell.kind.value,
            recipient.user_id,
        )
        return
    message = compose_mail(
        recipient, subject=bell.title, body=f"{bell.body}\n\n{bell.url}"
    )
    transaction.on_commit(partial(send, message))


class _SphereSubscriptionMail:
    """Promotional delivery authorized by the exact subscription selected.

    Deletion revokes queued mail even if the recipient becomes eligible again
    or opts in through a replacement subscription before delivery.
    """

    def __init__(
        self,
        *,
        subscription_id: int,
        recipient_id: int,
        sphere_name: str,
        unsubscribe_token: str,
    ) -> None:
        self._subscription_id = subscription_id
        self._recipient_id = recipient_id
        self._sphere_name = sphere_name
        self._token = unsubscribe_token

    def _authorized(self) -> bool:
        return SphereSubscription.objects.filter(
            pk=self._subscription_id,
            user_id=self._recipient_id,
            user__age_band=AgeBand.SIXTEEN_PLUS,
        ).exists()

    def deliver(self, recipient: Recipient, bell: Bell) -> None:
        if not self._authorized():
            logger.info("Promotional notification skipped: consent is no longer valid")
            return
        ring(recipient, bell)
        if not recipient.can_mail:
            logger.info("No deliverable address for promotional notification")
            return
        message = compose_mail(
            recipient,
            subject=bell.title,
            body=f"{bell.body}\n\n{bell.url}\n\n-- \n{self.footer()}",
            headers=self.headers(),
        )

        def _send_email() -> None:
            if not self._authorized():
                logger.info(
                    "Queued promotional email skipped: consent is no longer valid"
                )
                return
            send(message)

        transaction.on_commit(_send_email)

    def _url(self, name: str) -> str:
        return absolute_url(
            reverse(name, kwargs={"token": self._token}),
            domain=str(settings.ROOT_DOMAIN),
        )

    def footer(self) -> str:
        lines = [
            _("You get this email because you subscribe to %(sphere)s.") % {
                "sphere": self._sphere_name
            },
            _("Unsubscribe: %(url)s") % {"url": self._url("web:email-unsubscribe")},
        ]
        if address := settings.MAIL_POSTAL_ADDRESS:
            lines.append(address)
        return "\n".join(lines)

    def headers(self) -> dict[str, str]:
        return {
            "List-Unsubscribe": f"<{self._url('web:email-unsubscribe-confirm')}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }


class DjangoUserNotifier:
    """Every `notify_*` composes inside `speaking_to(recipient_user_id)`.

    It loads the recipient once (language and proven address) and holds
    their language while the copy is written. Delivery takes the recipient
    it yields and refuses one whose block has ended.
    """

    @staticmethod
    def notify_promoted(notification: PromotionNotification) -> None:
        with speaking_to(notification.recipient_user_id) as recipient:
            url = _session_url(notification.event_slug, notification.session_id)
            title = _("You're in: a spot opened in %(session)s") % {
                "session": notification.session_title
            }
            body = _(
                "A confirmed spot opened up and you have been enrolled automatically."
            )
            _deliver(
                recipient,
                Bell(
                    kind=NotificationKind.WAITLIST_PROMOTED,
                    title=title,
                    body=body,
                    url=url,
                    payload={"session_id": notification.session_id},
                ),
            )

    @staticmethod
    def notify_offered(notification: OfferNotification) -> None:
        with speaking_to(notification.recipient_user_id) as recipient:
            url = absolute_url(
                reverse(
                    "web:chronology:offer-claim",
                    kwargs={"token": notification.claim_token},
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
            _deliver(
                recipient,
                Bell(
                    kind=NotificationKind.WAITLIST_OFFER,
                    title=title,
                    body=body,
                    url=url,
                    payload={
                        "session_id": notification.session_id,
                        "claim_token": notification.claim_token,
                        "offer_expires_at": notification.offer_expires_at.isoformat(),
                    },
                ),
            )

    @staticmethod
    def notify_offer_expired(notification: PromotionNotification) -> None:
        # Flow-neutral: an expired row may be a waitlist offer or a seat a
        # leader held — nothing on it records which, so the copy fits both.
        with speaking_to(notification.recipient_user_id) as recipient:
            title = _("Your offer for %(session)s expired") % {
                "session": notification.session_title
            }
            body = _(
                "The seat was not claimed in time and has been released. You can "
                "sign up again if you are still interested."
            )
            _deliver(
                recipient,
                Bell(
                    kind=NotificationKind.OFFER_EXPIRED,
                    title=title,
                    body=body,
                    url=_session_url(notification.event_slug, notification.session_id),
                    payload={"session_id": notification.session_id},
                ),
            )

    @staticmethod
    def notify_party_invited(notification: PartyInviteNotification) -> None:
        with speaking_to(notification.recipient_user_id) as recipient:
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
            _deliver(
                recipient,
                Bell(
                    kind=NotificationKind.PARTY_INVITE,
                    title=title,
                    body=body,
                    url=absolute_url(
                        reverse("web:crowd:profile-parties"),
                        domain=settings.ROOT_DOMAIN,
                    ),
                ),
            )

    @staticmethod
    def notify_party_enrolled(notification: PartyEnrolledNotification) -> None:
        with speaking_to(notification.recipient_user_id) as recipient:
            url = _session_url(notification.event_slug, notification.session_id)
            title = _("%(leader)s enrolled you in %(session)s") % {
                "leader": notification.actor_name,
                "session": notification.session_title,
            }
            body = _(
                "You have a confirmed spot. If it does not fit your plans, you "
                "can cancel on the session page."
            )
            _deliver(
                recipient,
                Bell(
                    kind=NotificationKind.PARTY_ENROLLED,
                    title=title,
                    body=body,
                    url=url,
                    payload={"session_id": notification.session_id},
                ),
            )

    @staticmethod
    def notify_seat_held(notification: HeldSeatNotification) -> None:
        with speaking_to(notification.recipient_user_id) as recipient:
            url = absolute_url(
                reverse(
                    "web:chronology:offer-claim",
                    kwargs={"token": notification.claim_token},
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
            _deliver(
                recipient,
                Bell(
                    kind=NotificationKind.PARTY_SEAT_HELD,
                    title=title,
                    body=body,
                    url=url,
                    payload={
                        "session_id": notification.session_id,
                        "claim_token": notification.claim_token,
                        "offer_expires_at": notification.offer_expires_at.isoformat(),
                    },
                ),
            )

    @staticmethod
    def notify_email_verification(notification: EmailVerificationNotification) -> None:
        # The address being proven: nobody has proven it yet, by definition.
        with speaking_to(
            notification.recipient_user_id, mail_to=notification.recipient_email
        ) as recipient:
            url = absolute_url(
                reverse("web:crowd:email-link", kwargs={"token": notification.token}),
                domain=settings.ROOT_DOMAIN,
            )
            title = _("Confirm your email address")
            body = ngettext(
                "Use the link below to confirm this address for your account. "
                "The link is valid for %(hours)d hour.",
                "Use the link below to confirm this address for your account. "
                "The link is valid for %(hours)d hours.",
                _EMAIL_LINK_HOURS,
            ) % {"hours": _EMAIL_LINK_HOURS}
            _deliver(
                recipient,
                Bell(
                    kind=NotificationKind.EMAIL_VERIFICATION,
                    title=title,
                    body=body,
                    url=url,
                ),
            )

    @staticmethod
    def notify_email_change_requested(
        notification: EmailChangeRequestedNotification,
    ) -> None:
        # The pre-change address, so the cancel link reaches the account's
        # current owner rather than whoever asked for the change.
        with speaking_to(
            notification.recipient_user_id, mail_to=notification.recipient_email
        ) as recipient:
            url = absolute_url(
                reverse(
                    "web:crowd:email-link", kwargs={"token": notification.cancel_token}
                ),
                domain=settings.ROOT_DOMAIN,
            )
            title = _("Your email address is being changed")
            body = ngettext(
                "Someone asked to change your account's email address to "
                "%(new_address)s. If that was not you, cancel the change with the "
                "link below within %(hours)d hour.",
                "Someone asked to change your account's email address to "
                "%(new_address)s. If that was not you, cancel the change with the "
                "link below within %(hours)d hours.",
                _EMAIL_LINK_HOURS,
            ) % {"new_address": notification.new_address, "hours": _EMAIL_LINK_HOURS}
            _deliver(
                recipient,
                Bell(
                    kind=NotificationKind.EMAIL_CHANGE_REQUESTED,
                    title=title,
                    body=body,
                    url=url,
                    payload={"new_address": notification.new_address},
                ),
            )

    @staticmethod
    def notify_email_change_completed(
        notification: EmailChangeCompletedNotification,
    ) -> None:
        # The pre-change address; the row already holds the new one.
        with speaking_to(
            notification.recipient_user_id, mail_to=notification.recipient_email
        ) as recipient:
            title = _("Your email address was changed")
            body = _(
                "Your account's email address is now %(new_address)s. Sign-in and "
                "notifications use the new address from now on."
            ) % {"new_address": notification.new_address}
            _deliver(
                recipient,
                Bell(
                    kind=NotificationKind.EMAIL_CHANGE_COMPLETED,
                    title=title,
                    body=body,
                    url=absolute_url(
                        reverse("web:crowd:profile"), domain=settings.ROOT_DOMAIN
                    ),
                    payload={"new_address": notification.new_address},
                ),
            )

    @staticmethod
    def notify_printables_ready(notification: PrintablesReadyNotification) -> None:
        with speaking_to(notification.recipient_user_id) as recipient:
            url = absolute_url(
                reverse(
                    "web:chronology:event-print",
                    kwargs={"slug": notification.event_slug},
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
            _deliver(
                recipient,
                Bell(
                    kind=NotificationKind.PRINTABLES_READY,
                    title=title,
                    body=body,
                    url=url,
                    payload={"event_slug": notification.event_slug},
                ),
            )

    @staticmethod
    def notify_listing_interested(notification: ListingInterestedNotification) -> None:
        with speaking_to(notification.recipient_user_id) as recipient:
            title = _("%(name)s is interested in %(listing)s") % {
                "name": notification.responder_name,
                "listing": notification.listing_title,
            }
            _ring_board(
                notification,
                recipient=recipient,
                kind=NotificationKind.LISTING_INTERESTED,
                title=title,
                body=notification.message,
                url_name="web:board:responses",
            )

    @staticmethod
    def notify_listing_declined(notification: ListingDeclinedNotification) -> None:
        with speaking_to(notification.recipient_user_id) as recipient:
            title = _("Not this time: %(listing)s") % {
                "listing": notification.listing_title
            }
            _ring_board(
                notification,
                recipient=recipient,
                kind=NotificationKind.LISTING_DECLINED,
                title=title,
                body=notification.message
                or _("The author went with other people this time."),
            )

    @staticmethod
    def notify_listing_not_chosen(notification: ListingNotification) -> None:
        with speaking_to(notification.recipient_user_id) as recipient:
            title = _("%(listing)s has closed") % {
                "listing": notification.listing_title
            }
            _ring_board(
                notification,
                recipient=recipient,
                kind=NotificationKind.LISTING_NOT_CHOSEN,
                title=title,
                body=_("You weren't chosen this time. Thanks for responding."),
            )

    @staticmethod
    def notify_listing_changed(notification: ListingNotification) -> None:
        with speaking_to(notification.recipient_user_id) as recipient:
            title = _("%(listing)s has changed") % {
                "listing": notification.listing_title
            }
            _ring_board(
                notification,
                recipient=recipient,
                kind=NotificationKind.LISTING_CHANGED,
                title=title,
                body=_("The author edited the listing you responded to."),
            )

    @staticmethod
    def notify_sphere_event_published(
        notification: SphereEventPublishedNotification,
    ) -> None:
        with speaking_to(notification.recipient_user_id) as recipient:
            url = absolute_url(
                reverse(
                    "web:chronology:event", kwargs={"slug": notification.event_slug}
                ),
                domain=notification.sphere_domain,
            )
            title = _("%(sphere)s announced %(event)s") % {
                "sphere": notification.sphere_name,
                "event": notification.event_name,
            }
            body = _(
                "You subscribe to %(sphere)s. Its programme for %(event)s is up — "
                "open it to see what is on and sign up."
            ) % {"sphere": notification.sphere_name, "event": notification.event_name}
            _SphereSubscriptionMail(
                subscription_id=notification.subscription_id,
                recipient_id=notification.recipient_user_id,
                sphere_name=notification.sphere_name,
                unsubscribe_token=notification.unsubscribe_token,
            ).deliver(
                recipient,
                Bell(
                    kind=NotificationKind.SPHERE_EVENT_PUBLISHED,
                    title=title,
                    body=body,
                    url=url,
                    payload={"event_slug": notification.event_slug},
                ),
            )

    @staticmethod
    def notify_proposal_accepted(notification: ProposalAcceptedNotification) -> None:
        # Once per session and person: accepting again, or after a rejection
        # nobody was told about, is no news to them.
        with speaking_to(notification.recipient_user_id) as recipient:
            if already_told(
                notification.recipient_user_id,
                kind=NotificationKind.PROPOSAL_ACCEPTED,
                session_id=notification.session_id,
            ):
                logger.info(
                    "Acceptance of session %s already announced to user %s",
                    notification.session_id,
                    notification.recipient_user_id,
                )
                return
            title, body, url = _acceptance_copy(notification)
            _deliver(
                recipient,
                Bell(
                    kind=NotificationKind.PROPOSAL_ACCEPTED,
                    title=title,
                    body=body,
                    url=url,
                    payload={"session_id": notification.session_id},
                ),
            )

    @staticmethod
    def notify_anonymous_proposal_accepted(
        notification: AnonymousProposalAcceptedNotification,
    ) -> None:
        if not Session.objects.filter(
            pk=notification.session_id, acceptance_mailed_at__isnull=True
        ).update(acceptance_mailed_at=datetime.now(UTC)):
            logger.info(
                "Acceptance of session %s already mailed to its proposer",
                notification.session_id,
            )
            return
        # NOTE: unproven, unlike an account's address: the proposer gave this
        # address for status updates, and only an organizer can trigger this.
        with Voice(notification.language, address=notification.contact_email) as voice:
            title, body, url = _acceptance_copy(notification)
            message = compose_mail(voice, subject=title, body=f"{body}\n\n{url}")

        def _send_email() -> None:
            if send(message):
                logger.info(
                    "Acceptance of session %s mailed to its proposer in %s",
                    notification.session_id,
                    notification.language,
                )
            else:
                logger.warning(
                    "Acceptance of session %s not mailed to its proposer",
                    notification.session_id,
                )
                Session.objects.filter(pk=notification.session_id).update(
                    acceptance_mailed_at=None
                )

        transaction.on_commit(_send_email)

    @staticmethod
    def notify_shadowbanned_signup(notification: ShadowbanSignupNotification) -> None:
        with speaking_to(notification.recipient_user_id) as recipient:
            title = (
                _("A shadowbanned player joined %(session)s with you") % {
                    "session": notification.session_title
                }
                if notification.session_player_names
                else _("A shadowbanned player joined %(event)s") % {
                    "event": notification.event_name
                }
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
            parts.append(
                _("They have not been notified. Review the event if you need to.")
            )
            body = " ".join(parts)
            _deliver(
                recipient,
                Bell(
                    kind=NotificationKind.SHADOWBANNED_SIGNUP,
                    title=title,
                    body=body,
                    url=absolute_url(
                        reverse(
                            "web:chronology:event",
                            kwargs={"slug": notification.event_slug},
                        ),
                        domain=notification.sphere_domain,
                    ),
                    payload={"event_slug": notification.event_slug},
                ),
            )


class NotificationSubscriptionRepository:
    # ensure_sphere inserts with ignore_conflicts: an existing row (including a
    # concurrent first visit) is left exactly as it is, so a muted subscription
    # is never unmuted by auto-subscribe.
    @staticmethod
    def ensure_sphere(
        *, user_id: int, sphere_id: int, source: SubscriptionSource
    ) -> None:
        NotificationSubscription.objects.bulk_create(
            [
                NotificationSubscription(
                    user_id=user_id, sphere_id=sphere_id, source=source.value
                )
            ],
            ignore_conflicts=True,
        )

    @staticmethod
    def list_for_user(user_id: int) -> list[SubscriptionDTO]:
        return [
            SubscriptionDTO(pk=row.pk, muted=row.muted, sphere_name=row.sphere.name)
            for row in (
                NotificationSubscription.objects.filter(user_id=user_id)
                .select_related("sphere")
                .order_by(Lower("sphere__name"))
            )
        ]

    @staticmethod
    def set_muted(*, user_id: int, pk: int, muted: bool) -> bool:
        # Scoped by owner AND pk: someone else's subscription updates nothing
        # and the caller treats that as not found.
        updated = NotificationSubscription.objects.filter(
            user_id=user_id, pk=pk
        ).update(muted=muted)
        return bool(updated)
