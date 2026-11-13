"""How the server words what it writes into a case's thread.

Staff share one thread, so it is written in the site's language, not any
one reader's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext as _

from ludamus.pacts.moderation import ModerationStatus
from ludamus.pacts.staff_cases import (
    STAFF_THREAD_POST_MAX_LENGTH,
    CaseKind,
    CaseOpenedPost,
    DecisionPost,
    EmailInPost,
    EmailOutPost,
    StaffThreadPostClaims,
)

if TYPE_CHECKING:
    from datetime import datetime

    from ludamus.pacts.staff_cases import StaffThreadEntry, StaffThreadMessage

_AUDIENCE = "parley-post"
_TTL_SECONDS = 600


def _opened_by(kind: CaseKind) -> str:
    return {
        CaseKind.NOTICE: _("Notice of illegal content"),
        CaseKind.CHAT_REPORT: _("Chat report"),
        CaseKind.EMAIL: _("Email to staff"),
        CaseKind.STATEMENT: _("Statement of reasons"),
    }[kind]


def _worded(message: StaffThreadMessage, *, reference: str) -> tuple[str, str]:
    """Give the name the thread shows a message under, and its text."""
    match message:
        case CaseOpenedPost():
            return (
                _opened_by(message.kind),
                _("Case %(reference)s opened: %(title)s") % {
                    "reference": reference,
                    "title": message.title or "—",
                },
            )
        case EmailInPost():
            return (
                _("%(name)s (email)") % {"name": message.sender},
                _("Subject: %(subject)s") % {"subject": message.subject or "—"},
            )
        case EmailOutPost():
            return (
                _("%(name)s (email)") % {"name": message.staff.name},
                _("Replied to %(address)s.") % {"address": message.address},
            )
        case DecisionPost():
            heading = (
                _("Decided: acted on the content.")
                if message.status == ModerationStatus.ACTIONED
                else _("Decided: no action.")
            )
            return message.staff.name, f"{heading}\n\n{message.decision_text}"


def thread_post_claims(
    entry: StaffThreadEntry, *, now: datetime
) -> StaffThreadPostClaims:
    with translation.override(settings.LANGUAGE_CODE):
        name, body = _worded(entry.message, reference=entry.reference)
    issued = int(now.timestamp())
    return StaffThreadPostClaims(
        iss="ludamus",
        aud=_AUDIENCE,
        conversation=str(entry.thread_id),
        name=name,
        body=body[:STAFF_THREAD_POST_MAX_LENGTH],
        nonce=entry.nonce,
        iat=issued,
        exp=issued + _TTL_SECONDS,
    )
