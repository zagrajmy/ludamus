"""Protocols and DTOs for the shadowban (Safety & Comfort) feature.

A proposer keeps a personal shadowban list in their settings. Shadowbanned
players are never blocked — they enrol as usual — but the proposer is emailed
when one of them signs up to a session they run. Bottom-layer contracts
consumed by the `ShadowbanService` mill.
"""

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class ShadowbanCandidateDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    name: str
    slug: str
    is_shadowbanned: bool


class ShadowbanSignupTargetDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    presenter_id: int
    presenter_email: str
    session_title: str


class ShadowbanSignupNotification(BaseModel):
    recipient_user_id: int
    recipient_email: str
    session_id: int
    session_title: str
    player_names: list[str]


class ShadowbanRepositoryProtocol(Protocol):
    @staticmethod
    def list_candidates(owner_id: int) -> list[ShadowbanCandidateDTO]: ...
    @staticmethod
    def set_shadowban(*, owner_id: int, target_slug: str, banned: bool) -> None: ...
    @staticmethod
    def shadowban_by_identifier(*, owner_id: int, identifier: str) -> bool: ...
    @staticmethod
    def shadowbanned_user_ids(owner_id: int) -> set[int]: ...
    @staticmethod
    def read_signup_target(session_id: int) -> ShadowbanSignupTargetDTO | None: ...


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
    def notify_signups(
        self, *, session_id: int, signed_up: list[tuple[int, str]]
    ) -> None: ...
