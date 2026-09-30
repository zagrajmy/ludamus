"""Mails encounter guests calendar invites their mail client files itself.

Each message carries a ``text/calendar`` part with an iTIP method, which
Gmail, Outlook and Apple Mail act on without a click: a REQUEST adds or
updates the event, a CANCEL removes it. With ``ENCOUNTER_REPLY_EMAIL`` set,
each invite names a per-guest organizer address there, so a guest's
accept or decline comes back as a REPLY the app can trust.
"""

from __future__ import annotations

import logging
from base64 import b32encode
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, mailers
from django.db import transaction
from django.urls import reverse
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.formats import date_format
from django.utils.timezone import localtime
from django.utils.translation import gettext as _

from ludamus.links.absolute_url import absolute_url
from ludamus.pacts.calendar import CalendarEntry, CalendarInvite, Mailbox, ics_document
from ludamus.pacts.encounter import EncounterInviteReason

if TYPE_CHECKING:
    from ludamus.pacts.encounter import EncounterInvite


logger = logging.getLogger(__name__)

_REPLY_HMAC_NAMESPACE = "ludamus.encounter-reply"
_TOKEN_BYTES = 10


class DjangoEncounterInviteMailer:
    @staticmethod
    def send(invites: list[EncounterInvite]) -> None:
        deliverable = [invite for invite in invites if invite.attendee_email]
        if skipped := len(invites) - len(deliverable):
            logger.info(
                "Encounter %s: %d %s invites skipped, no email",
                invites[0].encounter.share_code,
                skipped,
                invites[0].reason,
            )
        if not deliverable:
            return
        share_code = deliverable[0].encounter.share_code
        reason = deliverable[0].reason
        # NOTE: rendered now, in the acting user's language and time zone —
        # users store neither, so an owner's edit reaches guests in theirs.
        messages = [_message(invite) for invite in deliverable]

        def _send() -> None:
            try:
                sent = mailers.default.send_messages(messages)
            except OSError:
                # NOTE: the change already committed; a lost invite must not
                # undo it, but it has to be visible.
                logger.exception(
                    "Encounter %s: %s invites not delivered", share_code, reason
                )
                return
            logger.info("Encounter %s: %s %s invites sent", share_code, sent, reason)

        transaction.on_commit(_send, robust=True)


class SignedReplyAddress:
    """`rsvp+<token>@…`, the token an HMAC of the invite's UID and guest."""

    @staticmethod
    def address_for(*, uid: str, attendee_email: str) -> str:
        local, __, domain = settings.ENCOUNTER_REPLY_EMAIL.partition("@")
        return f"{local}+{_token(uid, attendee_email)}@{domain}"

    @staticmethod
    def matches(*, address: str, uid: str, attendee_email: str) -> bool:
        local, __, domain = address.strip().lower().partition("@")
        expected_local, __, expected_domain = (
            settings.ENCOUNTER_REPLY_EMAIL.lower().partition("@")
        )
        base, __, token = local.partition("+")
        return (
            bool(expected_local)
            and base == expected_local
            and domain == expected_domain
            and constant_time_compare(token, _token(uid, attendee_email))
        )


def _token(uid: str, attendee_email: str) -> str:
    digest = salted_hmac(
        _REPLY_HMAC_NAMESPACE, f"{uid}\n{attendee_email.lower()}"
    ).digest()
    return b32encode(digest[:_TOKEN_BYTES]).decode().lower()


def _organizer(invite: EncounterInvite) -> Mailbox:
    if settings.ENCOUNTER_REPLY_EMAIL:
        email = SignedReplyAddress.address_for(
            uid=invite.uid, attendee_email=invite.attendee_email
        )
    else:
        __, email = parseaddr(settings.DEFAULT_FROM_EMAIL)
    return Mailbox(name=invite.organizer_name, email=email)


def _message(invite: EncounterInvite) -> EmailMultiAlternatives:
    encounter = invite.encounter
    url = absolute_url(
        reverse(
            "web:notice-board:encounter-detail",
            kwargs={"share_code": encounter.share_code},
        ),
        domain=invite.sphere_domain,
    )
    ics = ics_document(
        CalendarEntry(
            uid=invite.uid,
            title=encounter.title,
            start=encounter.start_time,
            end=invite.end_time,
            url=url,
            location=encounter.place,
            description=encounter.description,
        ),
        stamped_at=datetime.now(tz=UTC),
        invite=CalendarInvite(
            method=invite.method,
            sequence=invite.sequence,
            organizer=_organizer(invite),
            attendee=Mailbox(name=invite.attendee_name, email=invite.attendee_email),
            partstat=invite.partstat,
            rsvp=bool(settings.ENCOUNTER_REPLY_EMAIL),
        ),
    )
    message = EmailMultiAlternatives(
        subject=_subject(invite), body=_body(invite, url), to=[invite.attendee_email]
    )
    message.attach_alternative(
        ics, f"text/calendar; method={invite.method}; charset=utf-8"
    )
    return message


def _subject(invite: EncounterInvite) -> str:
    title = invite.encounter.title
    match invite.reason:
        case (
            EncounterInviteReason.CREATED
            | EncounterInviteReason.INVITED
            | EncounterInviteReason.JOINED
        ):
            return _("Invitation: %(title)s") % {"title": title}
        case EncounterInviteReason.CHANGED:
            return _("Updated: %(title)s") % {"title": title}
        case (
            EncounterInviteReason.LEFT
            | EncounterInviteReason.UNINVITED
            | EncounterInviteReason.DELETED
            | EncounterInviteReason.FULL
        ):
            return _("Cancelled: %(title)s") % {"title": title}


def _lead(invite: EncounterInvite) -> str:
    names = {"organizer": invite.organizer_name, "title": invite.encounter.title}
    match invite.reason:
        case EncounterInviteReason.CREATED:
            return _("Your encounter %(title)s is in your calendar.") % names
        case EncounterInviteReason.INVITED:
            return (
                _(
                    "%(organizer)s invites you to %(title)s. Accept in your "
                    "calendar or sign up on the encounter page."
                )
                % names
            )
        case EncounterInviteReason.JOINED:
            return _("You signed up for %(title)s.") % names
        case EncounterInviteReason.CHANGED:
            return _("%(organizer)s changed %(title)s.") % names
        case EncounterInviteReason.LEFT:
            return _("You are no longer signed up for %(title)s.") % names
        case EncounterInviteReason.UNINVITED:
            return _("You are no longer invited to %(title)s.") % names
        case EncounterInviteReason.DELETED:
            return _("%(organizer)s cancelled %(title)s.") % names
        case EncounterInviteReason.FULL:
            return (
                _("%(title)s is full, so your acceptance could not be saved.") % names
            )


def _body(invite: EncounterInvite, url: str) -> str:
    encounter = invite.encounter
    when = date_format(localtime(encounter.start_time), "DATETIME_FORMAT")
    lines = [_lead(invite), "", when]
    if encounter.place:
        lines.append(encounter.place)
    if invite.reason is not EncounterInviteReason.DELETED:
        lines += ["", url]
    return "\n".join(lines)
