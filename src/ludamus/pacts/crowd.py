"""Crowd subdomain contracts.

User identity (DTOs, data, repository protocols) and account lifecycle.
First lifecycle feature: claiming a managed (connected) profile — turning a
login-less companion row into the intended person's own self-login account,
on the same row, so enrollment history is preserved.
"""

from datetime import datetime
from enum import StrEnum
from typing import Protocol, TypedDict

from pydantic import BaseModel, ConfigDict


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
    manager_id: int | None = None
    name: str
    pk: int
    slug: str
    use_gravatar: bool
    user_type: UserType
    username: str


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
    def read_by_username(self, username: str) -> UserDTO: ...
    @staticmethod
    def update(user_slug: str, user_data: UserData) -> None: ...
    @staticmethod
    def email_exists(email: str, exclude_slug: str | None = None) -> bool: ...


class ConnectedUserRepositoryProtocol(Protocol):
    @staticmethod
    def create(manager_slug: str, user_data: UserData) -> None: ...
    @staticmethod
    def read_all(manager_slug: str) -> list[UserDTO]: ...
    @staticmethod
    def read(manager_slug: str, user_slug: str) -> UserDTO: ...
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
