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


class EventBanDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    user_name: str
    user_slug: str
    reason: str
    created_at: datetime


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
    def banned_user_ids(owner_id: int) -> set[int]: ...
    @staticmethod
    def banning_owner_ids(target_id: int) -> set[int]: ...
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


class EventBanRepositoryProtocol(Protocol):
    @staticmethod
    def list_by_event(event_id: int) -> list[EventBanDTO]: ...
    @staticmethod
    def is_banned(*, event_id: int, user_id: int) -> bool: ...
    @staticmethod
    def ban(*, event_id: int, identifier: str, reason: str) -> bool: ...
    @staticmethod
    def unban(*, event_id: int, ban_id: int) -> None: ...


class EventBanServiceProtocol(Protocol):
    def list_for_event(self, event_id: int) -> list[EventBanDTO]: ...
    def is_banned(self, *, event_id: int, user_id: int) -> bool: ...
    def ban(self, *, event_id: int, identifier: str, reason: str) -> bool: ...
    def unban(self, *, event_id: int, ban_id: int) -> None: ...


class ShadowbanNotifierProtocol(Protocol):
    def notify_shadowbanned_signup(
        self, notification: ShadowbanSignupNotification
    ) -> None: ...


class ShadowbanServiceProtocol(Protocol):
    def list_candidates(self, owner_id: int) -> list[ShadowbanCandidateDTO]: ...
    def banned_user_ids(self, owner_id: int) -> set[int]: ...
    def banning_presenter_ids(self, viewer_id: int) -> set[int]: ...
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
