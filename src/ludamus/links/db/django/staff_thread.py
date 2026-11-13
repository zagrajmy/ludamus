"""How the server words what it writes into a case's thread.

Staff share one thread, so it is written in the site's language, not any
one reader's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from ludamus.pacts.moderation import ModerationStatus
from ludamus.pacts.staff_cases import (
    STAFF_THREAD_POST_MAX_LENGTH,
    CaseKind,
    StaffThreadEvent,
    StaffThreadPostClaims,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.staff_cases import StaffThreadEntry

_AUDIENCE = "parley-post"
_TTL_SECONDS = 600
_SYSTEM_AUTHOR = "system"
_EMAIL_AUTHOR = "email"


def _opened_by(kind: str) -> str:
    return {
        CaseKind.NOTICE: _("Notice of illegal content"),
        CaseKind.CHAT_REPORT: _("Chat report"),
        CaseKind.EMAIL: _("Email to staff"),
        CaseKind.STATEMENT: _("Statement of reasons"),
    }[CaseKind(kind)]


def _attachments(count: int) -> str:
    return ngettext(
        "%(count)s attachment, kept in the staff mailbox",
        "%(count)s attachments, kept in the staff mailbox",
        count,
    ) % {"count": count}


def _worded(entry: StaffThreadEntry) -> tuple[str, str, str]:
    """Give the author id, name and text the thread shows for an entry."""
    details = entry.details
    staff_id = str(entry.author_id)
    match entry.event:
        case StaffThreadEvent.CASE_OPENED:
            return (
                _SYSTEM_AUTHOR,
                _opened_by(details["kind"]),
                _("Case %(reference)s opened: %(title)s") % {
                    "reference": details["reference"],
                    "title": entry.body or "—",
                },
            )
        case StaffThreadEvent.EMAIL_IN:
            count = int(details["attachments"])
            lines = [_("Subject: %(subject)s") % {"subject": details["subject"]}]
            lines.append(entry.body)
            if count:
                lines.append(_attachments(count))
            return (
                _EMAIL_AUTHOR,
                _("%(name)s (email)") % {"name": entry.author_name},
                "\n\n".join(lines),
            )
        case StaffThreadEvent.EMAIL_OUT:
            return (
                staff_id,
                _("%(name)s (email)") % {"name": entry.author_name},
                _("Sent to %(address)s:") % {"address": details["address"]}
                + f"\n\n{entry.body}",
            )
        case StaffThreadEvent.DECISION:
            heading = (
                _("Decided: acted on the content.")
                if details["status"] == ModerationStatus.ACTIONED
                else _("Decided: no action.")
            )
            return staff_id, entry.author_name, f"{heading}\n\n{entry.body}"
        case StaffThreadEvent.NOTE:
            return staff_id, entry.author_name, entry.body


def thread_post_claims(
    entry: StaffThreadEntry, *, now: datetime
) -> StaffThreadPostClaims:
    with translation.override(settings.LANGUAGE_CODE):
        author, name, body = _worded(entry)
    issued = int(now.timestamp())
    return StaffThreadPostClaims(
        iss="ludamus",
        aud=_AUDIENCE,
        conversation=str(entry.thread_id),
        author=author,
        name=name,
        body=body[:STAFF_THREAD_POST_MAX_LENGTH],
        source=entry.event,
        nonce=entry.nonce,
        retain_for=int(entry.retain_for.total_seconds()),
        iat=issued,
        exp=issued + _TTL_SECONDS,
    )
