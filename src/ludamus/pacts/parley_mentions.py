from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

PARLEY_MENTIONS_ISSUER = "parley"
PARLEY_MENTIONS_AUDIENCE = "ludamus-mentions"
PARLEY_MENTIONS_MAX = 50


class ParleyMention(BaseModel):
    """One mention of someone they have yet to read, as their inbox keeps it."""

    model_config = ConfigDict(frozen=True)

    room: str
    message: int
    author: str = Field(pattern=r"^\d+$")
    author_name: str = Field(alias="authorName")
    body: str
    at: int


class ParleyMentionClaims(BaseModel):
    """What the Worker signs when someone's mentions have waited unread."""

    iss: str
    aud: str
    sub: str = Field(pattern=r"^\d+$")
    iat: int
    exp: int
    mentions: list[ParleyMention] = Field(max_length=PARLEY_MENTIONS_MAX)


class ParleyMentionsOffError(Exception):
    """No secret is configured, so the app takes no mentions from the Worker."""


class ParleyMentionTokenError(Exception):
    """The token is not the Worker's, or no longer good."""


class ParleyMentionClaimsError(Exception):
    """The Worker signed something that is not a list of mentions."""


class ParleyMentionVerifierProtocol(Protocol):
    def verify(self, token: str, *, now: datetime) -> ParleyMentionClaims: ...


class ParleyMentionRecipientDTO(BaseModel):
    active: bool
    mailable: bool
    enabled: bool
    last_sent_at: datetime | None


class ParleyMentionLine(BaseModel):
    author_name: str
    body: str


class ParleyMentionChat(BaseModel):
    room_id: str
    title: str
    lines: list[ParleyMentionLine]


class ParleyMentionDigest(BaseModel):
    user_id: int
    chats: list[ParleyMentionChat]
    names: dict[str, str]
    unsubscribe_token: str


class ParleyMentionUnsubscribePayload(BaseModel):
    user_id: int


class ParleyMentionDeliveryStatus(StrEnum):
    SENT = "sent"
    SKIPPED = "skipped"
    THROTTLED = "throttled"


class ParleyMentionDelivery(BaseModel):
    status: ParleyMentionDeliveryStatus
    reason: str = ""
    retry_after: int | None = None


class ParleyMentionRepositoryProtocol(Protocol):
    @staticmethod
    def read_recipient(user_id: int) -> ParleyMentionRecipientDTO | None: ...

    @staticmethod
    def read_names(user_ids: set[int]) -> dict[int, str]: ...

    @staticmethod
    def record_sent(*, user_id: int, at: datetime) -> None: ...

    @staticmethod
    def read_enabled(user_id: int) -> bool: ...

    @staticmethod
    def set_enabled(*, user_id: int, enabled: bool) -> None: ...


class ParleyMentionMailerProtocol(Protocol):
    @staticmethod
    def send(digest: ParleyMentionDigest) -> bool: ...


class ParleyMentionUnsubscribeCodecProtocol(Protocol):
    def dumps(self, payload: ParleyMentionUnsubscribePayload) -> str: ...
    def loads(self, token: str) -> ParleyMentionUnsubscribePayload | None: ...


class ParleyMentionMailServiceProtocol(Protocol):
    def deliver(self, *, token: str, now: datetime) -> ParleyMentionDelivery: ...

    def read_enabled(self, user_id: int) -> bool: ...

    def set_enabled(self, *, user_id: int, enabled: bool) -> None: ...

    def read_unsubscribe_token(
        self, token: str
    ) -> ParleyMentionUnsubscribePayload | None: ...

    def unsubscribe_by_token(
        self, token: str
    ) -> ParleyMentionUnsubscribePayload | None: ...
