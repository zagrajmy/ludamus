"""Who a message is for, and the language it is written in: theirs.

Whoever triggers a message (an organizer, a party leader, an encounter
creator, a scheduled job) browses in their own language; the reader may not
share it. A reader never seen signed in, or with no account at all, reads
the site default, never the sender's language.

Every delivery in `delivery` takes a `Voice` (an address-only mail) or a
`Recipient` (an account's bell row and mail). Only `speaking_in` and
`speaking_to` hand one out, and it holds only inside their block, so a
message cannot go out composed in anyone's language but its reader's.
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


class NotSpeakingError(RuntimeError):
    """A message was delivered outside its reader's language."""


class Voice:
    """A reader's language, in force while a message is written in it."""

    __slots__ = ("_active", "_language")

    def __init__(self, language: str) -> None:
        self._language = language
        self._active: str | None = None

    @contextmanager
    def held(self) -> Generator[Voice]:
        with translation.override(self._language):
            self._active = translation.get_language()
            try:
                yield self
            finally:
                self._active = None

    def confirm(self) -> None:
        """Check the reader's language is the one in force.

        Raises:
            NotSpeakingError: outside a `speaking_in` block, or another
                language took over inside it.
        """
        if self._active is None:
            msg = f"Delivery outside a speaking block ({self._language} reader)"
            raise NotSpeakingError(msg)
        if (active := translation.get_language()) != self._active:
            msg = f"Delivery in {active} to a {self._language} reader"
            raise NotSpeakingError(msg)


@dataclass(frozen=True)
class AccountReader:
    user_id: int
    language: str
    deliverable_email: str


class Recipient:
    """An account's reader, while a message is being written for them."""

    __slots__ = ("_reader", "voice")

    def __init__(self, reader: AccountReader, voice: Voice) -> None:
        self._reader = reader
        self.voice = voice

    def confirm(self) -> AccountReader:
        """Hand over the reader to deliver to, once their language is in force.

        Returns:
            The reader the message was composed for.
        """
        self.voice.confirm()
        return self._reader


@contextmanager
def speaking_in(language: str) -> Generator[Voice]:
    with Voice(language).held() as voice:
        yield voice


@contextmanager
def speaking_to(reader: AccountReader) -> Generator[Recipient]:
    with speaking_in(reader.language) as voice:
        yield Recipient(reader, voice)


def _language(stored: str) -> str:
    return stored or settings.LANGUAGE_CODE


def account_reader(user_id: int, *, mail_to: str | None = None) -> AccountReader:
    """Read the account's language, and its address only once proven.

    Resolved here rather than at each producer, so a new notification cannot
    opt out of either rule by accident. `mail_to` names the address for the
    email-lifecycle notices alone: the one being proven, or the pre-change
    one the row no longer holds.
    """
    user = (
        User.objects.filter(pk=user_id)
        .only("language", "email", "email_verified")
        .first()
    )
    proven = user.email if user is not None and user.email_verified else ""
    return AccountReader(
        user_id=user_id,
        language=_language(user.language if user is not None else ""),
        deliverable_email=proven if mail_to is None else mail_to,
    )


def address_languages(emails: Collection[str]) -> dict[str, str]:
    """Each address in the language of its account, else the site default."""
    languages = {
        email.lower(): language
        for email, language in accounts_at(emails).values_list("email", "language")
    }
    return {email: _language(languages.get(email.lower(), "")) for email in emails}


def contact_language(stored: str) -> str:
    """Resolve the language someone with no account left with their address."""
    return _language(stored)
