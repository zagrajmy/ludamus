"""Mails encounter attendees calendar invites their mail client files itself.

Each message carries a ``text/calendar`` part with an iTIP method, which
Gmail, Outlook and Apple Mail act on without a click: a REQUEST adds or
updates the event, a CANCEL removes it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.urls import reverse
from django.utils.formats import date_format
from django.utils.timezone import localtime
from django.utils.translation import gettext as _

from ludamus.links.absolute_url import absolute_url
from ludamus.pacts.calendar import (
    CalendarEntry,
    CalendarInvite,
    InviteMethod,
    Mailbox,
    ics_document,
)
from ludamus.pacts.encounter import EncounterInviteReason

if TYPE_CHECKING:
    from ludamus.pacts.encounter import EncounterInvite


logger = logging.getLogger(__name__)

_CANCELLING = {EncounterInviteReason.LEFT, EncounterInviteReason.DELETED}


class DjangoEncounterInviteMailer:
    @staticmethod
    def send(invite: EncounterInvite) -> None:
        encounter = invite.encounter
        if not invite.recipient_email:
            logger.info(
                "Encounter %s: no email for a %s invite, skipped",
                encounter.share_code,
                invite.reason,
            )
            return
        message = _message(invite)

        def _send() -> None:
            try:
                message.send()
            except OSError:
                # The signup or edit already committed; a lost invite must
                # not undo it, but it has to be visible.
                logger.exception(
                    "Encounter %s: %s invite not delivered",
                    encounter.share_code,
                    invite.reason,
                )
                return
            logger.info(
                "Encounter %s: %s invite sent", encounter.share_code, invite.reason
            )

        transaction.on_commit(_send)


def _message(invite: EncounterInvite) -> EmailMultiAlternatives:
    encounter = invite.encounter
    url = absolute_url(
        reverse(
            "web:notice-board:encounter-detail",
            kwargs={"share_code": encounter.share_code},
        ),
        domain=invite.sphere_domain,
    )
    method = (
        InviteMethod.CANCEL if invite.reason in _CANCELLING else InviteMethod.REQUEST
    )
    __, sender = parseaddr(settings.DEFAULT_FROM_EMAIL)
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
            method=method,
            sequence=invite.sequence,
            organizer=Mailbox(name=invite.organizer_name, email=sender),
            attendee=Mailbox(name=invite.recipient_name, email=invite.recipient_email),
        ),
    )
    message = EmailMultiAlternatives(
        subject=_subject(invite), body=_body(invite, url), to=[invite.recipient_email]
    )
    message.attach_alternative(ics, f"text/calendar; method={method}; charset=utf-8")
    return message


def _subject(invite: EncounterInvite) -> str:
    title = invite.encounter.title
    match invite.reason:
        case EncounterInviteReason.JOINED:
            return _("Invitation: %(title)s") % {"title": title}
        case EncounterInviteReason.CHANGED:
            return _("Updated: %(title)s") % {"title": title}
        case EncounterInviteReason.LEFT | EncounterInviteReason.DELETED:
            return _("Cancelled: %(title)s") % {"title": title}


def _body(invite: EncounterInvite, url: str) -> str:
    encounter = invite.encounter
    match invite.reason:
        case EncounterInviteReason.JOINED:
            lead = _("You signed up for %(title)s.") % {"title": encounter.title}
        case EncounterInviteReason.CHANGED:
            lead = _("%(organizer)s changed %(title)s.") % {
                "organizer": invite.organizer_name,
                "title": encounter.title,
            }
        case EncounterInviteReason.LEFT:
            lead = _("You are no longer signed up for %(title)s.") % {
                "title": encounter.title
            }
        case EncounterInviteReason.DELETED:
            lead = _("%(organizer)s cancelled %(title)s.") % {
                "organizer": invite.organizer_name,
                "title": encounter.title,
            }
    when = date_format(localtime(encounter.start_time), "DATETIME_FORMAT")
    lines = [lead, "", when]
    if encounter.place:
        lines.append(encounter.place)
    if invite.reason is not EncounterInviteReason.DELETED:
        lines += ["", url]
    return "\n".join(lines)
