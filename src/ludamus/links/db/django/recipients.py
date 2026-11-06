"""Who a message is for, and the language it is written in: theirs.

Whoever triggers a message (an organizer, a party leader, an encounter
creator, a scheduled job) browses in their own language; the reader may not
share it. A reader never seen signed in, or with no account at all, reads
the site default, never the sender's language.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.conf import settings
from django.db.models.functions import Lower
from django.utils import translation

from ludamus.links.db.django.models import User
from ludamus.pacts.crowd import UserType

if TYPE_CHECKING:
    from collections.abc import Collection, Generator


@dataclass(frozen=True)
class Recipient:
    language: str
    deliverable_email: str


def _language(stored: str) -> str:
    return stored or settings.LANGUAGE_CODE


def account_recipient(user_id: int) -> Recipient:
    """Read the account's language, and its address only once proven.

    Resolved here rather than at each producer, so a new notification cannot
    opt out of either rule by accident.
    """
    user = (
        User.objects.filter(pk=user_id)
        .only("language", "email", "email_verified")
        .first()
    )
    if user is None:
        return Recipient(language=settings.LANGUAGE_CODE, deliverable_email="")
    return Recipient(
        language=_language(user.language),
        deliverable_email=user.email if user.email_verified else "",
    )


def address_recipients(emails: Collection[str]) -> dict[str, Recipient]:
    """Each address in the language of its account, else the site default.

    An address matches an account as encounter invitees do: case-insensitive,
    active accounts only. The address itself stays deliverable, because
    whoever named it chose to mail it, proven or not.
    """
    languages = dict(
        User.objects.annotate(address=Lower("email"))
        .filter(address__in={email.lower() for email in emails})
        .filter(user_type=UserType.ACTIVE)
        .values_list("address", "language")
    )
    return {
        email: Recipient(
            language=_language(languages.get(email.lower(), "")),
            deliverable_email=email,
        )
        for email in emails
    }


@contextmanager
def speaking_to(recipient: Recipient) -> Generator[Recipient]:
    with translation.override(recipient.language):
        yield recipient
