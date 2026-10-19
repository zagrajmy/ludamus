from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from ludamus.pacts.crowd import UserDTO
from ludamus.pacts.ids import EventBanId, EventId, SessionId, UserId


class ShadowbanMeetSessionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: SessionId
    title: str
    event_slug: str
    event_name: str
    sphere_name: str
    sphere_domain: str


class ShadowbanCandidateDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: UserId
    full_name: str
    username: str
    slug: str
    avatar_url: str
    is_shadowbanned: bool
    met_sessions: list[ShadowbanMeetSessionDTO] = Field(default_factory=list)

    @property
    def name(self) -> str:
        return self.full_name


class SessionShadowbanWarningDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserDTO
    shadowbanned_at: datetime


class EventBanDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: EventBanId
    user_name: str
    user_slug: str
    reason: str
    created_at: datetime


class ShadowbanHitDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipient_id: UserId
    banned_user_id: UserId
    in_session: bool


class ShadowbanEventSignupDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_slug: str
    event_name: str
    session_title: str
    sphere_domain: str
    hits: list[ShadowbanHitDTO]


class ShadowbanSignupNotification(BaseModel):
    recipient_user_id: UserId
    event_slug: str
    event_name: str
    session_title: str
    sphere_domain: str
    player_names: list[str]
    session_player_names: list[str]


class ShadowbanRepositoryProtocol(Protocol):
    @staticmethod
    def list_candidates(owner_id: UserId) -> list[ShadowbanCandidateDTO]: ...
    @staticmethod
    def banned_user_ids(owner_id: UserId) -> set[UserId]: ...
    @staticmethod
    def banning_owner_ids(target_id: UserId) -> set[UserId]: ...
    @staticmethod
    def set_shadowban(*, owner_id: UserId, target_slug: str, banned: bool) -> None: ...
    @staticmethod
    def shadowban_by_identifier(*, owner_id: UserId, identifier: str) -> bool: ...
    @staticmethod
    def read_event_signup(
        *, session_id: SessionId, signed_up_ids: list[UserId]
    ) -> ShadowbanEventSignupDTO | None: ...
    @staticmethod
    def list_session_shadowbanned(
        *, viewer_id: UserId, session_id: SessionId
    ) -> list[SessionShadowbanWarningDTO]: ...


class EventBanRepositoryProtocol(Protocol):
    @staticmethod
    def list_by_event(event_id: EventId) -> list[EventBanDTO]: ...
    @staticmethod
    def is_banned(*, event_id: EventId, user_id: UserId) -> bool: ...
    @staticmethod
    def banned_event_ids(
        *, event_ids: set[EventId], user_id: UserId
    ) -> set[EventId]: ...
    @staticmethod
    def ban(*, event_id: EventId, identifier: str, reason: str) -> bool: ...
    @staticmethod
    def unban(*, event_id: EventId, ban_id: EventBanId) -> None: ...


class EventBanServiceProtocol(Protocol):
    def list_for_event(self, event_id: EventId) -> list[EventBanDTO]: ...
    def is_banned(self, *, event_id: EventId, user_id: UserId) -> bool: ...
    def banned_event_ids(
        self, *, event_ids: set[EventId], user_id: UserId
    ) -> set[EventId]: ...
    def ban(self, *, event_id: EventId, identifier: str, reason: str) -> bool: ...
    def unban(self, *, event_id: EventId, ban_id: EventBanId) -> None: ...


class ShadowbanNotifierProtocol(Protocol):
    def notify_shadowbanned_signup(
        self, notification: ShadowbanSignupNotification
    ) -> None: ...


class ShadowbanServiceProtocol(Protocol):
    def list_candidates(self, owner_id: UserId) -> list[ShadowbanCandidateDTO]: ...
    def banned_user_ids(self, owner_id: UserId) -> set[UserId]: ...
    def banning_owner_ids(self, target_id: UserId) -> set[UserId]: ...
    def set_shadowban(
        self, *, owner_id: UserId, target_slug: str, banned: bool
    ) -> None: ...
    def add_by_identifier(self, *, owner_id: UserId, identifier: str) -> bool: ...
    def list_session_warnings(
        self, *, viewer_id: UserId, session_id: SessionId
    ) -> list[SessionShadowbanWarningDTO]: ...
    def notify_signups(
        self, *, session_id: SessionId, signed_up: list[tuple[UserId, str]]
    ) -> None: ...
