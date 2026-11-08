"""The only place a bell row is created or a mail is built and sent.

Each primitive takes the `Voice` or `Recipient` its message was composed
under and confirms that language is still in force, so copy written in the
sender's language cannot reach a reader. An ast-grep rule
(`deliver-through-a-recipient`) keeps Notification rows and Django mail out
of every other module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from django.core.mail import EmailMessage, EmailMultiAlternatives, mailers

from ludamus.links.db.django.models import Notification

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from ludamus.links.db.django.recipients import Recipient, Voice
    from ludamus.pacts.legacy import NotificationKind

type Mail = EmailMessage


@dataclass(frozen=True, kw_only=True)
class Bell:
    """What one bell row says, and where it leads (empty url: the overlay)."""

    kind: NotificationKind
    title: str
    body: str
    url: str
    payload: Mapping[str, str | int] = field(default_factory=dict)


def _row(bell: Bell, recipient_id: int) -> Notification:
    return Notification(
        recipient_id=recipient_id,
        kind=bell.kind.value,
        title=bell.title,
        body=bell.body,
        url=bell.url,
        payload=dict(bell.payload),
    )


def ring(recipient: Recipient, bell: Bell) -> None:
    """Create the bell row for the account the copy was written for."""
    recipient.confirm()
    _row(bell, recipient.user_id).save()


def ring_as_written(*, recipient_ids: Iterable[int], bell: Bell) -> int:
    """Ring each recipient's bell with text a person wrote, as they wrote it.

    The one delivery that takes no `Recipient`: an organizer's announcement
    or a notice staff send from the admin is someone's own words in a
    language they chose. ast-grep rules allow it only in those modules and
    keep translation out of them.

    Returns:
        How many bells rang.
    """
    rows = Notification.objects.bulk_create(
        [_row(bell, recipient_id) for recipient_id in recipient_ids], batch_size=500
    )
    return len(rows)


def _subject_line(title: str) -> str:
    """Fold a title onto one line for a mail subject.

    Titles carry user text (session, listing, event names), and mail refuses
    a header with a line break in it (BadHeaderError).
    """
    return " ".join(title.split())


def compose_mail(
    speaker: Voice | Recipient,
    *,
    subject: str,
    body: str,
    headers: Mapping[str, str] | None = None,
) -> EmailMessage:
    return EmailMessage(
        subject=_subject_line(subject),
        body=body,
        to=[speaker.mail_to()],
        headers=dict(headers or {}),
    )


def compose_calendar_mail(
    speaker: Voice | Recipient, *, subject: str, body: str, ics: str, method: str
) -> EmailMultiAlternatives:
    message = EmailMultiAlternatives(
        subject=_subject_line(subject), body=body, to=[speaker.mail_to()]
    )
    message.attach_alternative(ics, f"text/calendar; method={method}; charset=utf-8")
    return message


def send(message: EmailMessage) -> bool:
    """Send one notice, best-effort: the change it announces has committed.

    Returns:
        Whether the mail server took it; a refusal is the caller's to log.
    """
    return bool(message.send(fail_silently=True))


def send_all(messages: Sequence[EmailMessage]) -> int:
    """Send in one connection.

    Raises:
        OSError: the mail server could not be reached.
    """
    return mailers.default.send_messages(list(messages)) or 0
