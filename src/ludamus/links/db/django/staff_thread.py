"""How the server words what it writes into a staff case's thread.

Staff share one thread, so it is written in the site's language, not any
one reader's.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext

from ludamus.pacts.staff_cases import (
    STAFF_THREAD_POST_MAX_LENGTH,
    ModerationAction,
    ModerationGround,
    StaffThreadEvent,
    StaffThreadPostClaims,
)

if TYPE_CHECKING:
    from django.utils.functional import _StrPromise

    from ludamus.pacts.staff_cases import StaffThreadEntry

_AUDIENCE = "parley-post"
_TTL_SECONDS = 600
_SYSTEM_AUTHOR = "system"
_EMAIL_AUTHOR = "email"

ACTION_LABELS: dict[ModerationAction, _StrPromise] = {
    ModerationAction.NONE: gettext_lazy("No action"),
    ModerationAction.HIDE: gettext_lazy("Hide content"),
    ModerationAction.REMOVE: gettext_lazy("Remove content"),
    ModerationAction.MUTE_24H: gettext_lazy("Mute for 24 hours"),
    ModerationAction.SUSPEND: gettext_lazy("Suspend account"),
}
GROUND_LABELS: dict[ModerationGround, _StrPromise] = {
    ModerationGround.DISRUPTION: gettext_lazy(
        "Terms § 4.1 point 4: disrupting the service"
    ),
    ModerationGround.MISUSE: gettext_lazy(
        "Terms § 4.1 point 5: using the service against its purpose"
    ),
    ModerationGround.RIGHTS: gettext_lazy(
        "Terms § 4.1 point 6: violating other users' rights"
    ),
    ModerationGround.UNLAWFUL_OR_INDECENT: gettext_lazy(
        "Terms § 4.1 point 7: unlawful or indecent content"
    ),
    ModerationGround.ILLEGAL: gettext_lazy("Illegal content"),
}


def _attachments(count: int) -> str:
    return ngettext(
        "%(count)s attachment, kept in the staff mailbox",
        "%(count)s attachments, kept in the staff mailbox",
        count,
    ) % {"count": count}


def _worded(entry: StaffThreadEntry) -> tuple[str, str, str]:
    """Give the author id, name and text the thread shows for an entry."""
    details = entry.details
    staff_id = "" if entry.author_id is None else str(entry.author_id)
    match entry.event:
        case StaffThreadEvent.CASE_OPENED:
            reason = entry.body or _("no reason given")
            return (
                _SYSTEM_AUTHOR,
                _("Chat report"),
                _("Reported in %(room)s. Reason: %(reason)s") % {
                    "room": details.get("room", ""),
                    "reason": reason,
                },
            )
        case StaffThreadEvent.EMAIL_IN:
            count = int(details.get("attachments", "0"))
            lines = [
                _("Subject: %(subject)s") % {"subject": details.get("subject", "")},
                entry.body,
            ]
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
                _("Sent to %(address)s:") % {"address": details.get("address", "")}
                + f"\n\n{entry.body}",
            )
        case StaffThreadEvent.DECISION:
            return (
                staff_id,
                entry.author_name,
                _("Decision: %(action)s. Ground: %(ground)s.") % {
                    "action": ACTION_LABELS[ModerationAction(details["action"])],
                    "ground": GROUND_LABELS[ModerationGround(details["ground"])],
                },
            )
        case StaffThreadEvent.NOTE:
            return staff_id, entry.author_name, entry.body


def thread_post_claims(
    entry: StaffThreadEntry, *, now: datetime | None = None
) -> StaffThreadPostClaims:
    with translation.override(settings.LANGUAGE_CODE):
        author, name, body = _worded(entry)
    issued = int((now or datetime.now(UTC)).timestamp())
    return StaffThreadPostClaims(
        iss="ludamus",
        aud=_AUDIENCE,
        conversation=str(entry.conversation_id),
        author=author,
        name=name,
        body=body[:STAFF_THREAD_POST_MAX_LENGTH],
        source=entry.event,
        nonce=entry.nonce,
        retain_for=int(entry.retain_for.total_seconds()),
        iat=issued,
        exp=issued + _TTL_SECONDS,
    )
