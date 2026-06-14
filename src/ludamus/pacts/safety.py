"""Protocols and DTOs for the shadowban (Safety & Comfort) feature."""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.legacy import UserDTO


class ShadowbanCandidateDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    name: str
    slug: str
    is_shadowbanned: bool


class SessionShadowbanWarningDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserDTO
    shadowbanned_at: datetime


class ShadowbanHitDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    presenter_id: int
    presenter_email: str
    banned_user_id: int


class ShadowbanEventSignupDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_slug: str
    event_name: str
    hits: list[ShadowbanHitDTO]


class ShadowbanSignupNotification(BaseModel):
    recipient_user_id: int
    recipient_email: str
    event_slug: str
    event_name: str
    player_names: list[str]


class ShadowbanRepositoryProtocol(Protocol):
    @staticmethod
    def list_candidates(owner_id: int) -> list[ShadowbanCandidateDTO]: ...
    @staticmethod
    def set_shadowban(*, owner_id: int, target_slug: str, banned: bool) -> None: ...
    @staticmethod
    def shadowban_by_identifier(*, owner_id: int, identifier: str) -> bool: ...
    @staticmethod
    def read_event_signup(
        *, session_id: int, signed_up_ids: list[int]
    ) -> ShadowbanEventSignupDTO | None: ...
    @staticmethod
    def list_session_shadowbanned(
        *, viewer_id: int, session_id: int
    ) -> list[SessionShadowbanWarningDTO]: ...


class ShadowbanNotifierProtocol(Protocol):
    def notify_shadowbanned_signup(
        self, notification: ShadowbanSignupNotification
    ) -> None: ...


class ShadowbanServiceProtocol(Protocol):
    def list_candidates(self, owner_id: int) -> list[ShadowbanCandidateDTO]: ...
    def set_shadowban(
        self, *, owner_id: int, target_slug: str, banned: bool
    ) -> None: ...
    def add_by_identifier(self, *, owner_id: int, identifier: str) -> bool: ...
    def list_session_warnings(
        self, *, viewer_id: int, session_id: int
    ) -> list[SessionShadowbanWarningDTO]: ...
    def notify_signups(
        self, *, session_id: int, signed_up: list[tuple[int, str]]
    ) -> None: ...
