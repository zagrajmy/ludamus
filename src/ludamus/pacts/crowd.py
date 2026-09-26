"""Crowd subdomain contracts.

User identity (DTOs, data, repository protocols) and account lifecycle.
First lifecycle feature: claiming a managed companion profile — turning a
login-less companion row into the intended person's own self-login account,
on the same row, so enrollment history is preserved.
"""

from datetime import datetime
from enum import StrEnum
from typing import Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.ids import UserId

MAX_CONNECTED_USERS = 6  # Maximum number of connected users per manager
MAX_AVATAR_URL_LENGTH = 500  # Column width; a longer provider URL is dropped


class UserType(StrEnum):
    ACTIVE = "active"
    CONNECTED = "connected"
    ANONYMOUS = "anonymous"


class UserDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    avatar_url: str
    date_joined: datetime
    discord_username: str
    email: str
    full_name: str
    is_active: bool
    is_authenticated: bool
    is_staff: bool
    is_superuser: bool
    name: str
    pk: UserId
    slug: str
    use_gravatar: bool
    user_type: UserType
    username: str


class CompanionDTO(UserDTO):
    # The claim token is a bearer credential for taking over the profile, so
    # it lives only on the manager-facing companion read model — never on
    # the app-wide UserDTO.
    claim_token: str = ""


class UserData(TypedDict, total=False):
    avatar_url: str
    discord_username: str
    email: str
    is_active: bool
    name: str
    password: str
    slug: str
    use_gravatar: bool
    user_type: UserType
    username: str


class UserRepositoryProtocol(Protocol):
    @staticmethod
    def create(user_data: UserData) -> None: ...
    def read(self, slug: str) -> UserDTO: ...
    def read_by_id(self, pk: int) -> UserDTO: ...
    def read_by_ids(self, pks: list[int]) -> list[UserDTO]: ...
    def read_by_username(self, username: str) -> UserDTO: ...
    def read_by_email(self, email: str) -> UserDTO: ...
    @staticmethod
    def update(user_slug: str, user_data: UserData) -> None: ...
    @staticmethod
    def email_exists(email: str, exclude_slug: str | None = None) -> bool: ...
    @staticmethod
    def slug_exists(slug: str) -> bool: ...


class CompanionRepositoryProtocol(Protocol):
    @staticmethod
    def create(manager_slug: str, user_data: UserData) -> None: ...
    @staticmethod
    def read_all(manager_slug: str) -> list[CompanionDTO]: ...
    @staticmethod
    def read(manager_slug: str, user_slug: str) -> CompanionDTO: ...
    @staticmethod
    def delete(manager_slug: str, user_slug: str) -> None: ...
    @staticmethod
    def update(manager_slug: str, user_slug: str, user_data: UserData) -> None: ...


class ClaimableProfileDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    slug: str
    manager_name: str


class ClaimOutcome(StrEnum):
    CONVERTED = "converted"
    ALREADY_AUTHENTICATED = "already_authenticated"
    INVALID = "invalid"


class ClaimResultDTO(BaseModel):
    outcome: ClaimOutcome
    user_slug: str = ""


class ClaimRepositoryProtocol(Protocol):
    @staticmethod
    def issue_token(*, manager_slug: str, user_slug: str, token: str) -> bool: ...
    @staticmethod
    def read_claimable(token: str) -> ClaimableProfileDTO | None: ...
    @staticmethod
    def username_exists(username: str) -> bool: ...
    @staticmethod
    def convert(*, token: str, username: str) -> str | None: ...


class ClaimServiceProtocol(Protocol):
    def issue(self, *, manager_slug: str, user_slug: str) -> str | None: ...
    def read_claimable(self, token: str) -> ClaimableProfileDTO | None: ...
    def redeem(self, *, token: str, username: str) -> ClaimResultDTO: ...


class SphereDomainRepositoryProtocol(Protocol):
    @staticmethod
    def domain_exists(domain: str) -> bool: ...


class IdentityDTO(BaseModel):
    """A signed-in person as the identity provider (WorkOS) reports them."""

    provider_user_id: str
    email: str
    email_verified: bool
    name: str
    avatar_url: str
    # The Auth0 user_id the WorkOS import carried over as external_id; empty
    # for anyone who signed up after the move.
    legacy_id: str


class AuthenticationDTO(BaseModel):
    identity: IdentityDTO
    # The AuthKit session behind this login, needed to end it at logout.
    session_id: str


class LoginDTO(BaseModel):
    user: UserDTO
    claim_outcome: ClaimOutcome | None = None
    session_id: str


class IdentityRejectedError(Exception):
    """The identity provider refused the authorization code."""


class IdentityProviderProtocol(Protocol):
    def authorization_url(
        self, *, redirect_uri: str, state: str, sign_up: bool
    ) -> str: ...
    def authenticate(self, code: str) -> AuthenticationDTO: ...
    def logout_url(self, *, session_id: str, return_to: str) -> str: ...


class CrowdAuthServiceProtocol(Protocol):
    def login_url(self, *, redirect_uri: str, state: str, sign_up: bool) -> str: ...
    def complete_login(self, *, code: str, claim_token: str = "") -> LoginDTO: ...
    def logout_url(self, *, session_id: str, return_to: str) -> str: ...
    def is_known_sphere_domain(self, domain: str) -> bool: ...


class ProfileParticipationRepositoryProtocol(Protocol):
    @staticmethod
    def confirmed_count(user_id: int) -> int: ...


class AvatarUrlProviderProtocol(Protocol):
    def __call__(self, email: str) -> str | None: ...


class AvatarPageDTO(BaseModel):
    user: UserDTO
    gravatar_url: str | None
    has_provider_avatar: bool


class ProfileServiceProtocol(Protocol):
    def read(self, user_slug: str) -> UserDTO: ...
    def confirmed_participations_count(self, user_id: int) -> int: ...
    def email_in_use(self, email: str, *, exclude_slug: str) -> bool: ...
    def update(self, user_slug: str, data: UserData) -> None: ...
    def read_avatar(self, user_slug: str) -> AvatarPageDTO: ...
    def set_avatar_preference(self, user_slug: str, *, use_gravatar: bool) -> None: ...


class CompanionsServiceProtocol(Protocol):
    def list_companions(self, manager_slug: str) -> list[CompanionDTO]: ...
    def read(self, *, manager_slug: str, user_slug: str) -> CompanionDTO: ...
    def create(self, *, manager_slug: str, user_data: UserData) -> None: ...
    def update(
        self, *, manager_slug: str, user_slug: str, user_data: UserData
    ) -> None: ...
    def delete(self, *, manager_slug: str, user_slug: str) -> None: ...
