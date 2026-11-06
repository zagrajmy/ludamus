"""Who a message is for, and the language it is written in: theirs.

Whoever triggers a message (an organizer, a party leader, an encounter
creator, a scheduled job) browses in their own language; the reader may not
share it. A reader never seen signed in, or with no account at all, reads
the site default, never the sender's language.

Delivery takes a `Recipient`, which only `speaking_to` makes and which holds
only inside its block, so a message cannot go out composed in anyone's
language but its reader's. Text a person wrote, sent as written (an
announcement, an admin notice), is the one exception: `ring_as_written`.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from django.conf import settings
from django.db.models.functions import Lower
from django.utils import translation

from ludamus.links.db.django.models import User
from ludamus.pacts.crowd import UserType

if TYPE_CHECKING:
    from collections.abc import Collection, Generator


class NotSpeakingError(RuntimeError):
    """A message went out past its reader's language, or to someone else."""


@dataclass(frozen=True)
class Reader:
    language: str
    deliverable_email: str
    user_id: int | None = None


class _Seal:
    pass


_SEAL = _Seal()


@final
class Recipient:
    """A reader, while a message is being written for them."""

    __slots__ = ("_reader", "_voice")

    def __init__(self, reader: Reader, *, seal: _Seal) -> None:
        if seal is not _SEAL:
            msg = "A Recipient comes only from speaking_to"
            raise TypeError(msg)
        self._reader = reader
        self._voice: str | None = None

    @classmethod
    @contextmanager
    def speaking_to(cls, reader: Reader) -> Generator[Recipient]:
        recipient = cls(reader, seal=_SEAL)
        with translation.override(reader.language):
            recipient._voice = translation.get_language()
            try:
                yield recipient
            finally:
                recipient._voice = None

    def confirm(self) -> Reader:
        """Hand over the reader to deliver to, once their language is in force.

        Returns:
            The reader the message was composed for.

        Raises:
            NotSpeakingError: past the `speaking_to` block, or another
                language took over inside it.
        """
        if self._voice is None or translation.get_language() != self._voice:
            msg = (
                f"Delivery outside the reader's language: {self._reader.language}"
                f" expected, {translation.get_language()} active"
            )
            raise NotSpeakingError(msg)
        return self._reader


speaking_to = Recipient.speaking_to


def _language(stored: str) -> str:
    return stored or settings.LANGUAGE_CODE


def account_reader(user_id: int, *, mail_to: str | None = None) -> Reader:
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
    return Reader(
        language=_language(user.language if user is not None else ""),
        deliverable_email=proven if mail_to is None else mail_to,
        user_id=user_id,
    )


def address_readers(emails: Collection[str]) -> dict[str, Reader]:
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
        email: Reader(
            language=_language(languages.get(email.lower(), "")),
            deliverable_email=email,
        )
        for email in emails
    }


def contact_reader(*, email: str, language: str) -> Reader:
    """Someone with no account, in the language they left with their address."""
    return Reader(language=_language(language), deliverable_email=email)
