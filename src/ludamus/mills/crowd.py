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
    AvatarPageDTO,
    ClaimOutcome,
    ClaimResultDTO,
    ClaimServiceProtocol,
    CompanionsServiceProtocol,
    CrowdAuthServiceProtocol,
    ProfileServiceProtocol,
    UserData,
)
from ludamus.pacts.services import DatabaseConstraintError

if TYPE_CHECKING:
    from ludamus.pacts.crowd import (
        AvatarUrlProviderProtocol,
        ClaimableProfileDTO,
        ClaimRepositoryProtocol,
        ConnectedUserDTO,
        ConnectedUserRepositoryProtocol,
        ProfileParticipationRepositoryProtocol,
        SphereDomainRepositoryProtocol,
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
        try:
            with self._transaction.savepoint():
                self._users.create(data)
        except DatabaseConstraintError:
            # A concurrent callback for the same identity inserted the row
            # between our read_by_username miss and this insert; adopt it.
            pass
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


class ProfileService(ProfileServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        users: UserRepositoryProtocol,
        participations: ProfileParticipationRepositoryProtocol,
        avatar_url: AvatarUrlProviderProtocol,
    ) -> None:
        self._transaction = transaction
        self._users = users
        self._participations = participations
        self._avatar_url = avatar_url

    def read(self, user_slug: str) -> UserDTO:
        return self._users.read(user_slug)

    def confirmed_participations_count(self, user_id: int) -> int:
        return self._participations.confirmed_count(user_id)

    def email_in_use(self, email: str, *, exclude_slug: str) -> bool:
        return self._users.email_exists(email, exclude_slug=exclude_slug)

    def update(self, user_slug: str, data: UserData) -> None:
        with self._transaction.atomic():
            self._users.update(user_slug, data)

    def read_avatar(self, user_slug: str) -> AvatarPageDTO:
        user = self._users.read(user_slug)
        return AvatarPageDTO(
            user=user,
            gravatar_url=self._avatar_url(user.email),
            has_auth0_avatar=bool(user.avatar_url),
        )

    def set_avatar_preference(self, user_slug: str, *, use_gravatar: bool) -> None:
        with self._transaction.atomic():
            self._users.update(user_slug, UserData(use_gravatar=use_gravatar))


class CompanionsService(CompanionsServiceProtocol):
    def __init__(
        self,
        transaction: TransactionProtocol,
        companions: ConnectedUserRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._companions = companions

    def list_companions(self, manager_slug: str) -> list[ConnectedUserDTO]:
        return self._companions.read_all(manager_slug)

    def read(self, *, manager_slug: str, user_slug: str) -> ConnectedUserDTO:
        return self._companions.read(manager_slug, user_slug)

    def create(self, *, manager_slug: str, user_data: UserData) -> None:
        with self._transaction.atomic():
            self._companions.create(manager_slug, user_data=user_data)

    def update(self, *, manager_slug: str, user_slug: str, user_data: UserData) -> None:
        with self._transaction.atomic():
            self._companions.update(manager_slug, user_slug, user_data)

    def delete(self, *, manager_slug: str, user_slug: str) -> None:
        with self._transaction.atomic():
            self._companions.delete(manager_slug, user_slug)
