"""The only place a bell row is saved or a mail is built and sent.

Each primitive takes the `Voice` or `Recipient` its message was composed
under and confirms that language is still in force, so copy written in the
sender's language cannot reach a reader. An ast-grep rule
(`deliver-through-a-recipient`) keeps Notification rows and Django mail out
of every other module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.mail import EmailMessage, EmailMultiAlternatives, mailers

from ludamus.links.db.django.models import Notification

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from ludamus.links.db.django.recipients import AccountReader, Recipient, Voice
    from ludamus.pacts.legacy import NotificationKind

type Mail = EmailMessage


def ring(
    recipient: Recipient,
    *,
    kind: NotificationKind,
    title: str,
    body: str,
    url: str,
    payload: Mapping[str, str | int],
) -> AccountReader:
    """Save the bell row for the reader the copy was written for.

    Returns:
        That reader, for the caller to mail.
    """
    reader = recipient.confirm()
    Notification.objects.create(
        recipient_id=reader.user_id,
        kind=kind.value,
        title=title,
        body=body,
        url=url,
        payload=dict(payload),
    )
    return reader


def ring_as_written(
    *,
    recipient_ids: Iterable[int],
    kind: str,
    title: str,
    body: str,
    url: str,
    payload: Mapping[str, str | int] | None = None,
) -> int:
    """Ring each recipient's bell with text a person wrote, as they wrote it.

    The one delivery that takes no `Recipient`: an organizer's announcement
    or a notice staff send from the admin is someone's own words in a
    language they chose. ast-grep rules allow it only at those call sites
    and never with translated copy in its arguments.

    Returns:
        How many bells rang.
    """
    rows = Notification.objects.bulk_create(
        [
            Notification(
                recipient_id=recipient_id,
                kind=kind,
                title=title,
                body=body,
                url=url,
                payload=dict(payload or {}),
            )
            for recipient_id in recipient_ids
        ],
        batch_size=500,
    )
    return len(rows)


def subject_line(title: str) -> str:
    """Fold a title onto one line for a mail subject.

    Titles carry user text (session, listing, event names), and mail refuses
    a header with a line break in it (BadHeaderError).
    """
    return " ".join(title.split())


def compose_mail(
    voice: Voice,
    *,
    subject: str,
    body: str,
    to: str,
    headers: Mapping[str, str] | None = None,
) -> EmailMessage:
    voice.confirm()
    return EmailMessage(
        subject=subject_line(subject), body=body, to=[to], headers=dict(headers or {})
    )


def compose_calendar_mail(
    voice: Voice, *, subject: str, body: str, to: str, ics: str, method: str
) -> EmailMultiAlternatives:
    voice.confirm()
    message = EmailMultiAlternatives(subject=subject_line(subject), body=body, to=[to])
    message.attach_alternative(ics, f"text/calendar; method={method}; charset=utf-8")
    return message


def send(message: EmailMessage) -> bool:
    return bool(message.send(fail_silently=True))


def send_all(messages: Sequence[EmailMessage]) -> int:
    """Send in one connection.

    Raises:
        OSError: the mail server could not be reached.
    """
    return mailers.default.send_messages(list(messages)) or 0
