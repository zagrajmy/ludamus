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
    CaseOpenedPost,
    DecisionPost,
    EmailInPost,
    EmailOutPost,
    NotePost,
    StaffThreadPostClaims,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.staff_cases import StaffThreadEntry, StaffThreadMessage

_AUDIENCE = "parley-post"
_TTL_SECONDS = 600
_SYSTEM_AUTHOR = "system"
_EMAIL_AUTHOR = "email"


def _opened_by(kind: CaseKind) -> str:
    return {
        CaseKind.NOTICE: _("Notice of illegal content"),
        CaseKind.CHAT_REPORT: _("Chat report"),
        CaseKind.EMAIL: _("Email to staff"),
        CaseKind.STATEMENT: _("Statement of reasons"),
    }[kind]


def _worded(message: StaffThreadMessage, *, reference: str) -> tuple[str, str, str]:
    """Give the author id, name and text the thread shows for a message."""
    match message:
        case CaseOpenedPost():
            return (
                _SYSTEM_AUTHOR,
                _opened_by(message.kind),
                _("Case %(reference)s opened: %(title)s") % {
                    "reference": reference,
                    "title": message.title or "—",
                },
            )
        case EmailInPost():
            lines = [_("Subject: %(subject)s") % {"subject": message.subject}]
            lines.append(message.body)
            if message.attachments:
                lines.append(
                    ngettext(
                        "%(count)s attachment, kept in the staff mailbox",
                        "%(count)s attachments, kept in the staff mailbox",
                        message.attachments,
                    )
                    % {"count": message.attachments}
                )
            return (
                _EMAIL_AUTHOR,
                _("%(name)s (email)") % {"name": message.sender},
                "\n\n".join(lines),
            )
        case EmailOutPost():
            return (
                str(message.staff.pk),
                _("%(name)s (email)") % {"name": message.staff.name},
                _("Sent to %(address)s:") % {"address": message.address}
                + f"\n\n{message.body}",
            )
        case DecisionPost():
            heading = (
                _("Decided: acted on the content.")
                if message.status == ModerationStatus.ACTIONED
                else _("Decided: no action.")
            )
            return (
                str(message.staff.pk),
                message.staff.name,
                f"{heading}\n\n{message.decision_text}",
            )
        case NotePost():
            return str(message.staff.pk), message.staff.name, message.body


def thread_post_claims(
    entry: StaffThreadEntry, *, now: datetime
) -> StaffThreadPostClaims:
    with translation.override(settings.LANGUAGE_CODE):
        author, name, body = _worded(entry.message, reference=entry.reference)
    issued = int(now.timestamp())
    return StaffThreadPostClaims(
        iss="ludamus",
        aud=_AUDIENCE,
        conversation=str(entry.thread_id),
        author=author,
        name=name,
        body=body[:STAFF_THREAD_POST_MAX_LENGTH],
        nonce=entry.nonce,
        iat=issued,
        exp=issued + _TTL_SECONDS,
    )
