"""Crowd subdomain contracts.

Profiles and account lifecycle. First feature: claiming a managed (connected)
profile — turning a login-less companion row into the intended person's own
self-login account, on the same row, so enrollment history is preserved.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict


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
