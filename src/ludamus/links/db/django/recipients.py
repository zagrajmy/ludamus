"""Who a message is for, and the language it is written in: theirs.

Whoever triggers a message (an organizer, a party leader, an encounter
creator, a scheduled job) browses in their own language; the reader may not
share it. A companion account reads its manager's language. A reader with
no language on record reads English, never the sender's language.

Every delivery in `delivery` takes a `Voice` (an address-only mail) or a
`Recipient` (an account's bell row and mail). Only `speaking_to(user_id)`
makes a Recipient, from the account's language and proven address,
and either token confirms only inside its block, so a message cannot go out
composed in anyone's language but its reader's.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from django.utils import translation

from ludamus.links.db.django.crowd import accounts_at
from ludamus.links.db.django.models import User

if TYPE_CHECKING:
    from collections.abc import Collection, Generator
    from types import TracebackType


_UNRECORDED_LANGUAGE = "en"


class NotSpeakingError(RuntimeError):
    """A message was delivered outside its reader's language."""


class NoAddressError(RuntimeError):
    """A mail was composed for a reader with no address to mail."""


class Voice:
    """An address's language, in force while a message to it is written.

    For mail to an address alone (an encounter guest, an anonymous
    proposer); an account's goes through `speaking_to`. An empty language
    (none on record) is English. One block at a time.
    """

    __slots__ = ("_active", "_address", "_language", "_override")

    def __init__(self, language: str, *, address: str) -> None:
        # NOTE: not settings.LANGUAGE_CODE: a reader we know nothing about
        # is likelier to read English than the site's own language.
        self._language = language or _UNRECORDED_LANGUAGE
        self._address = address
        self._override: translation.override | None = None
        self._active: str | None = None

    def __enter__(self) -> Self:
        if self._override is not None:
            msg = "A Voice holds one block at a time"
            raise RuntimeError(msg)
        self._override = translation.override(self._language)
        self._override.__enter__()
        self._active = translation.get_language()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        override, self._override, self._active = self._override, None, None
        if override is not None:
            override.__exit__(exc_type, exc, traceback)

    def confirm(self) -> None:
        """Check this language is the one in force.

        Raises:
            NotSpeakingError: outside the voice's block, or another language
                took over inside it.
        """
        if self._active is None:
            msg = f"Delivery outside a speaking block ({self._language} reader)"
            raise NotSpeakingError(msg)
        if (active := translation.get_language()) != self._active:
            msg = f"Delivery in {active} to a {self._language} reader"
            raise NotSpeakingError(msg)

    def mail_to(self) -> str:
        """Hand over the address, once its language is in force.

        Returns:
            The address the message was composed for.
        """
        self.confirm()
        return self._address


@dataclass(frozen=True)
class _AccountReader:
    user_id: int
    language: str
    deliverable_email: str


def _account_reader(user_id: int, *, mail_to: str | None) -> _AccountReader:
    user = (
        User.objects.filter(pk=user_id)
        .select_related("manager")
        .only("language", "email", "email_verified", "manager__language")
        .first()
    )
    if user is None:
        return _AccountReader(
            user_id=user_id, language="", deliverable_email=mail_to or ""
        )
    proven = user.email if user.email_verified else ""
    return _AccountReader(
        user_id=user_id,
        language=(user.manager or user).language,
        deliverable_email=proven if mail_to is None else mail_to,
    )


class Recipient:
    """An account, while a message is being written for them."""

    __slots__ = ("_reader", "_voice")

    def __init__(self, reader: _AccountReader, voice: Voice) -> None:
        self._reader = reader
        self._voice = voice

    @property
    def user_id(self) -> int:
        return self._reader.user_id

    @property
    def can_mail(self) -> bool:
        return bool(self._reader.deliverable_email)

    def confirm(self) -> None:
        """Check the reader's language is the one in force.

        Raises:
            NotSpeakingError: past the `speaking_to` block, or another
                language took over inside it.
        """
        self._voice.confirm()

    def mail_to(self) -> str:
        """Hand over the reader's address, once their language is in force.

        Returns:
            The address to mail.

        Raises:
            NoAddressError: the reader has no address anyone proved.
        """
        if not (address := self._voice.mail_to()):
            msg = f"User {self.user_id} has no deliverable address"
            raise NoAddressError(msg)
        return address


@contextmanager
def speaking_to(user_id: int, *, mail_to: str | None = None) -> Generator[Recipient]:
    """Compose for this account, in its language, to its proven address.

    Loads the account once and resolves both rules here rather than at each
    producer, so a new notification cannot opt out of either by accident.
    `mail_to` names the address for the email-lifecycle notices alone: the
    one being proven, or the pre-change one the row no longer holds.
    """
    reader = _account_reader(user_id, mail_to=mail_to)
    with Voice(reader.language, address=reader.deliverable_email) as voice:
        yield Recipient(reader, voice)


def address_languages(emails: Collection[str]) -> dict[str, str]:
    """Each address in the language of its account; empty when it has none."""
    languages = {
        email.lower(): language
        for email, language in accounts_at(emails).values_list("email", "language")
    }
    return {email: languages.get(email.lower(), "") for email in emails}
