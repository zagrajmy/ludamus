"""Crowd subdomain business logic.

Profiles and account lifecycle. Django-free; receives specific repo protocols
plus a transaction. First feature: claiming a managed profile.
"""

from __future__ import annotations

import logging
import secrets
from contextlib import suppress
from typing import TYPE_CHECKING

from ludamus.mills.slugs import slug_base, unique_slug
from ludamus.pacts import NotFoundError
from ludamus.pacts.crowd import (
    MAX_AVATAR_URL_LENGTH,
    AvatarPageDTO,
    ClaimOutcome,
    ClaimResultDTO,
    ClaimServiceProtocol,
    CompanionsServiceProtocol,
    CrowdAuthServiceProtocol,
    LoginDTO,
    ProfileServiceProtocol,
    UserData,
)
from ludamus.pacts.services import DatabaseConstraintError

if TYPE_CHECKING:
    from ludamus.pacts.crowd import (
        AvatarUrlProviderProtocol,
        ClaimableProfileDTO,
        ClaimRepositoryProtocol,
        CompanionDTO,
        CompanionRepositoryProtocol,
        IdentityDTO,
        IdentityProviderProtocol,
        ProfileParticipationRepositoryProtocol,
        SphereDomainRepositoryProtocol,
        UserDTO,
        UserRepositoryProtocol,
    )
    from ludamus.pacts.services import TransactionProtocol


logger = logging.getLogger(__name__)

AUTH0_USERNAME_PREFIX = "auth0|"
WORKOS_USERNAME_PREFIX = "workos|"


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


class LegacyAccountLinker:
    """Finds the Auth0-era account behind a first WorkOS login and claims it.

    TODO: https://github.com/zagrajmy/ludamus/issues/1402 — delete once no
    active account is left on an auth0| username.
    """

    def __init__(self, *, users: UserRepositoryProtocol) -> None:
        self._users = users

    def adopt(self, identity: IdentityDTO, *, username: str) -> UserDTO | None:
        if (legacy := self._find(identity)) is None:
            return None
        self._users.update(legacy.slug, {"username": username})
        logger.info("Linked legacy account %s to %s", legacy.slug, username)
        return self._users.read(legacy.slug)

    def _find(self, identity: IdentityDTO) -> UserDTO | None:
        # The import's external_id is authoritative: when it is set but its
        # account is gone, an email match would land on someone else's row.
        if identity.legacy_id:
            with suppress(NotFoundError):
                return self._users.read_by_username(
                    f"{AUTH0_USERNAME_PREFIX}{identity.legacy_id}"
                )
            return None
        if not identity.email_verified or not identity.email:
            return None
        with suppress(NotFoundError):
            user = self._users.read_by_email(identity.email)
            if user.username.startswith(AUTH0_USERNAME_PREFIX):
                # SAFETY: Auth0 never verified the stored address, so this
                # match is weaker than external_id; keep it visible.
                logger.warning("Linking legacy account %s by verified email", user.slug)
                return user
        return None


class CrowdAuthService(CrowdAuthServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        users: UserRepositoryProtocol,
        spheres: SphereDomainRepositoryProtocol,
        claims: ClaimServiceProtocol,
        identity: IdentityProviderProtocol,
        legacy_accounts: LegacyAccountLinker,
    ) -> None:
        self._transaction = transaction
        self._users = users
        self._spheres = spheres
        self._claims = claims
        self._identity = identity
        self._legacy_accounts = legacy_accounts

    def login_url(self, *, redirect_uri: str, state: str, sign_up: bool) -> str:
        return self._identity.authorization_url(
            redirect_uri=redirect_uri, state=state, sign_up=sign_up
        )

    def logout_url(self, *, session_id: str, return_to: str) -> str:
        return self._identity.logout_url(session_id=session_id, return_to=return_to)

    def complete_login(self, *, code: str, claim_token: str = "") -> LoginDTO:
        authentication = self._identity.authenticate(code)
        identity = authentication.identity
        username = f"{WORKOS_USERNAME_PREFIX}{identity.provider_user_id}"
        avatar_url = _avatar_url(identity)
        with self._transaction.atomic():
            user = self._read_by_username(username) or self._legacy_accounts.adopt(
                identity, username=username
            )
            claim_outcome: ClaimOutcome | None = None
            if claim_token:
                result = self._claims.redeem(token=claim_token, username=username)
                claim_outcome = result.outcome
                if result.outcome == ClaimOutcome.CONVERTED:
                    user = self._users.read(result.user_slug)
            if user is None:
                user = self._create_user(
                    username=username,
                    create_data=UserData(
                        slug=slug_base(identity.provider_user_id),
                        username=username,
                        email=identity.email,
                        avatar_url=avatar_url,
                        name=identity.name,
                    ),
                )
            user = self._sync_identity(user, identity=identity, avatar_url=avatar_url)
        return LoginDTO(
            user=user, claim_outcome=claim_outcome, session_id=authentication.session_id
        )

    def _read_by_username(self, username: str) -> UserDTO | None:
        with suppress(NotFoundError):
            return self._users.read_by_username(username)
        return None

    def _create_user(self, *, username: str, create_data: UserData) -> UserDTO:
        data = create_data.copy()
        if self._users.email_exists(data.get("email", "")):
            data["email"] = ""
        # NOTE: the slug is unique table-wide, so a CONNECTED or ANONYMOUS
        # row can own the one the provider id slugifies to; uniquifying also
        # caps it to the SlugField width, which an over-long id would blow.
        data["slug"] = unique_slug(
            base=data.get("slug", ""), default="user", exists=self._users.slug_exists
        )
        try:
            with self._transaction.savepoint():
                self._users.create(data)
        except DatabaseConstraintError:
            # NOTE: a concurrent callback for the same identity may have
            # inserted the row between our read_by_username miss and this
            # insert; adopt it. With no such row the insert failed for a real
            # reason, so let the database error surface, not a NotFoundError.
            with suppress(NotFoundError):
                return self._users.read_by_username(username)
            raise
        return self._users.read_by_username(username)

    def _sync_identity(
        self, user: UserDTO, *, identity: IdentityDTO, avatar_url: str
    ) -> UserDTO:
        updates = UserData()
        if (
            identity.email
            and user.email != identity.email
            and not self._users.email_exists(identity.email, exclude_slug=user.slug)
        ):
            updates["email"] = identity.email
        if avatar_url and user.avatar_url != avatar_url:
            updates["avatar_url"] = avatar_url
        if identity.name and not user.name.strip():
            updates["name"] = identity.name
        if not updates:
            return user
        self._users.update(user.slug, updates)
        return self._users.read(user.slug)

    def is_known_sphere_domain(self, domain: str) -> bool:
        return self._spheres.domain_exists(domain)


def _avatar_url(identity: IdentityDTO) -> str:
    # A URL truncated to the column width would be broken; better no avatar.
    if len(identity.avatar_url) > MAX_AVATAR_URL_LENGTH:
        logger.warning(
            "Identity avatar dropped: %s chars exceeds %s",
            len(identity.avatar_url),
            MAX_AVATAR_URL_LENGTH,
        )
        return ""
    return identity.avatar_url


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
            has_provider_avatar=bool(user.avatar_url),
        )

    def set_avatar_preference(self, user_slug: str, *, use_gravatar: bool) -> None:
        with self._transaction.atomic():
            self._users.update(user_slug, UserData(use_gravatar=use_gravatar))


class CompanionsService(CompanionsServiceProtocol):
    def __init__(
        self, transaction: TransactionProtocol, companions: CompanionRepositoryProtocol
    ) -> None:
        self._transaction = transaction
        self._companions = companions

    def list_companions(self, manager_slug: str) -> list[CompanionDTO]:
        return self._companions.read_all(manager_slug)

    def read(self, *, manager_slug: str, user_slug: str) -> CompanionDTO:
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
