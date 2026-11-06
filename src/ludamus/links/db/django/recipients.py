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
from django.utils import translation

from ludamus.links.db.django.crowd import accounts_at
from ludamus.links.db.django.models import User

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


def address_languages(emails: Collection[str]) -> dict[str, str]:
    """Each address in the language of its account, else the site default."""
    languages = {
        email.lower(): language
        for email, language in accounts_at(emails).values_list("email", "language")
    }
    return {email: _language(languages.get(email.lower(), "")) for email in emails}


@contextmanager
def speaking_to(recipient: Recipient) -> Generator[Recipient]:
    with translation.override(recipient.language):
        yield recipient
