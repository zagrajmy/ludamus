"""Crowd subdomain business logic.

Profiles and account lifecycle. Django-free; receives specific repo protocols
plus a transaction. First feature: claiming a managed profile.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from ludamus.pacts.crowd import ClaimOutcome, ClaimResultDTO

if TYPE_CHECKING:
    from ludamus.pacts.crowd import ClaimableProfileDTO, ClaimRepositoryProtocol
    from ludamus.pacts.services import TransactionProtocol


def _token() -> str:
    return secrets.token_urlsafe(48)


class ClaimService:
    """Issue and redeem links that turn a managed profile into a real account."""

    def __init__(
        self, transaction: TransactionProtocol, claims: ClaimRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._claims = claims

    def issue(self, *, manager_slug: str, user_slug: str) -> str | None:
        token = _token()
        with self._transaction.atomic():
            if not self._claims.issue_token(
                manager_slug=manager_slug, user_slug=user_slug, token=token
            ):
                return None
        return token

    def read_claimable(self, token: str) -> ClaimableProfileDTO | None:
        return self._claims.read_claimable(token)

    def redeem(
        self, *, token: str, username: str, email: str, avatar_url: str
    ) -> ClaimResultDTO:
        with self._transaction.atomic():
            if self._claims.read_claimable(token) is None:
                return ClaimResultDTO(outcome=ClaimOutcome.INVALID)
            # The recipient already authenticates as someone else; converting
            # this row would collide on username. Refusing keeps the
            # same-row conversion clean — merging into an existing account is a
            # deliberate non-goal for now.
            if self._claims.username_exists(username):
                return ClaimResultDTO(outcome=ClaimOutcome.ALREADY_AUTHENTICATED)
            slug = self._claims.convert(
                token=token, username=username, email=email, avatar_url=avatar_url
            )
            if slug is None:
                return ClaimResultDTO(outcome=ClaimOutcome.INVALID)
            return ClaimResultDTO(outcome=ClaimOutcome.CONVERTED, user_slug=slug)
