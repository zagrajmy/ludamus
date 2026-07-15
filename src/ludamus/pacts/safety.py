from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from ludamus.pacts.crowd import UserDTO


class ShadowbanMeetSessionDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: int
    title: str
    event_slug: str


class ShadowbanCandidateDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
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

    pk: int
    user_name: str
    user_slug: str
    reason: str
    created_at: datetime


class ShadowbanHitDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recipient_id: int
    recipient_email: str
    banned_user_id: int
    in_session: bool


class ShadowbanEventSignupDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_slug: str
    event_name: str
    session_title: str
    hits: list[ShadowbanHitDTO]


class ShadowbanSignupNotification(BaseModel):
    recipient_user_id: int
    recipient_email: str
    event_slug: str
    event_name: str
    session_title: str
    player_names: list[str]
    session_player_names: list[str]


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
    def banned_event_ids(*, event_ids: set[int], user_id: int) -> set[int]: ...
    @staticmethod
    def ban(*, event_id: int, identifier: str, reason: str) -> bool: ...
    @staticmethod
    def unban(*, event_id: int, ban_id: int) -> None: ...


class EventBanServiceProtocol(Protocol):
    def list_for_event(self, event_id: int) -> list[EventBanDTO]: ...
    def is_banned(self, *, event_id: int, user_id: int) -> bool: ...
    def banned_event_ids(self, *, event_ids: set[int], user_id: int) -> set[int]: ...
    def ban(self, *, event_id: int, identifier: str, reason: str) -> bool: ...
    def unban(self, *, event_id: int, ban_id: int) -> None: ...


class ShadowbanNotifierProtocol(Protocol):
    def notify_shadowbanned_signup(
        self, notification: ShadowbanSignupNotification
    ) -> None: ...


class ShadowbanServiceProtocol(Protocol):
    def list_candidates(self, owner_id: int) -> list[ShadowbanCandidateDTO]: ...
    def banned_user_ids(self, owner_id: int) -> set[int]: ...
    def banning_owner_ids(self, target_id: int) -> set[int]: ...
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
