"""Crowd subdomain business logic.

Profiles and account lifecycle. Django-free; receives specific repo protocols
plus a transaction. First feature: claiming a managed profile.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import (
    AuthProvisionDTO,
    ClaimOutcome,
    ClaimResultDTO,
    ClaimServiceProtocol,
    CrowdAuthServiceProtocol,
)

if TYPE_CHECKING:
    from ludamus.pacts.crowd import (
        ClaimableProfileDTO,
        ClaimRepositoryProtocol,
        SphereDomainRepositoryProtocol,
        UserData,
        UserDTO,
        UserRepositoryProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


def _token() -> str:
    return secrets.token_urlsafe(48)


class ClaimService(ClaimServiceProtocol):
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

    def redeem(self, *, token: str, username: str) -> ClaimResultDTO:
        with self._transaction.atomic():
            # The recipient already authenticates as someone else; converting
            # this row would collide on the unique username. Refusing keeps the
            # same-row conversion clean — merging into an existing account is a
            # deliberate non-goal for now.
            if self._claims.username_exists(username):
                return ClaimResultDTO(outcome=ClaimOutcome.ALREADY_AUTHENTICATED)
            # convert returns None for an unknown/spent token, so it is the sole
            # authority on validity — no separate read-back probe.
            if (slug := self._claims.convert(token=token, username=username)) is None:
                return ClaimResultDTO(outcome=ClaimOutcome.INVALID)
            return ClaimResultDTO(outcome=ClaimOutcome.CONVERTED, user_slug=slug)


class CrowdAuthService(CrowdAuthServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        users: UserRepositoryProtocol,
        spheres: SphereDomainRepositoryProtocol,
        claims: ClaimServiceProtocol,
    ) -> None:
        self._transaction = transaction
        self._users = users
        self._spheres = spheres
        self._claims = claims

    def provision_user(
        self, *, username: str, create_data: UserData, claim_token: str = ""
    ) -> AuthProvisionDTO:
        claim_outcome: ClaimOutcome | None = None
        if claim_token:
            result = self._claims.redeem(token=claim_token, username=username)
            claim_outcome = result.outcome
            if result.outcome == ClaimOutcome.CONVERTED:
                return AuthProvisionDTO(
                    user=self._users.read(result.user_slug), claim_outcome=claim_outcome
                )
        try:
            user = self._users.read_by_username(username)
        except NotFoundError:
            user = self._create_user(username=username, create_data=create_data)
        return AuthProvisionDTO(user=user, claim_outcome=claim_outcome)

    def _create_user(self, *, username: str, create_data: UserData) -> UserDTO:
        data = create_data.copy()
        if self._users.email_exists(data.get("email", "")):
            data["email"] = ""
        with self._transaction.atomic():
            self._users.create(data)
        return self._users.read_by_username(username)

    def sync_identity(self, *, user_slug: str, data: UserData) -> UserDTO:
        updates = data.copy()
        if "email" in updates and self._users.email_exists(
            updates["email"], exclude_slug=user_slug
        ):
            del updates["email"]
        if updates:
            with self._transaction.atomic():
                self._users.update(user_slug, updates)
        return self._users.read(user_slug)

    def is_known_sphere_domain(self, domain: str) -> bool:
        return self._spheres.domain_exists(domain)
