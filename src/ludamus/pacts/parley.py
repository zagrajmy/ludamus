from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ParleyRoomKind(StrEnum):
    SPHERE = "sphere"
    SESSION = "session"


class ParleyRole(StrEnum):
    MANAGER = "manager"
    MEMBER = "member"


class ParleyRoomDTO(BaseModel):
    id: str
    kind: ParleyRoomKind
    title: str
    can_write: bool = Field(serialization_alias="canWrite")
    can_moderate: bool = Field(default=False, serialization_alias="canModerate")
    session_id: int | None = Field(default=None, exclude=True)
    ends_at: int | None = Field(default=None, exclude=True)


class ParleyAccessDTO(BaseModel):
    sphere_id: int
    sphere_name: str
    user_id: int
    user_name: str
    user_avatar_url: str
    rooms: list[ParleyRoomDTO]
    is_manager: bool


class ParleyConversationKind(StrEnum):
    DIRECT = "direct"
    GROUP = "group"


class ParleyMemberState(StrEnum):
    ACTIVE = "active"
    REQUEST = "request"
    LEFT = "left"


class ParleyPersonDTO(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    id: str
    name: str
    avatar_url: str = Field(serialization_alias="avatarUrl")


class ParleyConversationDTO(BaseModel):
    """A conversation as one member sees it."""

    model_config = ConfigDict(serialize_by_alias=True)

    id: str
    kind: ParleyConversationKind
    # A group's own title; a direct conversation is named after the other person.
    title: str
    state: ParleyMemberState
    can_write: bool = Field(serialization_alias="canWrite")
    is_admin: bool = Field(serialization_alias="isAdmin")
    members: list[ParleyPersonDTO]


class ParleyBootstrapDTO(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    sphere: dict[str, str]
    user: dict[str, str]
    rooms: list[ParleyRoomDTO]
    # Whether direct messages and groups are open to this person at all.
    can_message: bool = Field(default=False, serialization_alias="canMessage")
    conversations: list[ParleyConversationDTO] = Field(default_factory=list)
    capability_token: str = Field(serialization_alias="capabilityToken")
    agent_host: str = Field(serialization_alias="agentHost")


class ParleySessionGrant(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    ends_at: int = Field(serialization_alias="endsAt")
    writable: bool


class ParleyCapabilityClaims(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    iss: str
    aud: str
    sub: str
    sphere: str
    name: str
    avatar: str
    role: ParleyRole
    # Only a member's own sessions: a manager's role covers every room of the
    # sphere, so their token stays the same size however many rooms it has.
    sessions: dict[str, ParleySessionGrant]
    read_only_after: int = Field(serialization_alias="readOnlyAfter")
    retain_for: int = Field(serialization_alias="retainFor")
    # Whether this person may use direct and group conversations at all:
    # signed in, active and 16 or over.
    direct: bool = False
    iat: int
    exp: int
    jti: str


# The Worker's deny-list entry: every pass of `sphere` issued to `sub` before
# `revoked_before` is void, and "*" stands for everyone in the sphere.
REVOKE_EVERYONE = "*"


class ParleyRevocationClaims(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    iss: str
    aud: str
    sphere: str
    sub: str
    revoked_before: int = Field(serialization_alias="revokedBefore")
    iat: int
    # Once every pass it voids has expired on its own, the entry is moot.
    exp: int
    jti: str


class ParleyReportData(BaseModel):
    sphere_id: int
    user_id: int
    room_id: str
    message_id: int = Field(gt=0)
    reason: str = Field(max_length=255)


class ParleyTimeWindow(BaseModel):
    now: datetime
    retained_after: datetime
    writable_after: datetime


class ParleyRepositoryProtocol(Protocol):
    @staticmethod
    def read_access(
        *, sphere_id: int, user_id: int, window: ParleyTimeWindow
    ) -> ParleyAccessDTO | None: ...

    def create_report(
        self, *, data: ParleyReportData, window: ParleyTimeWindow
    ) -> bool: ...

    @staticmethod
    def read_event_sphere_id(event_id: int) -> int | None: ...

    @staticmethod
    def list_chat_sphere_ids() -> list[int]: ...


class ParleySignerProtocol(Protocol):
    def sign(
        self,
        claims: (
            ParleyCapabilityClaims | ParleyMembershipClaims | ParleyRevocationClaims
        ),
    ) -> str: ...


class ParleyRevocationOutboxProtocol(Protocol):
    # Delivers once the surrounding transaction commits, so a pass issued
    # from the state being replaced cannot postdate the cutoff.
    def schedule(self, *, sphere_ids: list[int], subject: str) -> None: ...


class ParleyRevocationServiceProtocol(Protocol):
    def revoke_event_user(self, *, event_id: int, user_id: int) -> None: ...

    def revoke_user(self, *, user_id: int) -> None: ...

    def revoke_sphere(self, *, sphere_id: int) -> None: ...


class ParleyServiceProtocol(Protocol):
    def bootstrap(
        self, *, sphere_id: int, user_id: int, now: datetime
    ) -> ParleyBootstrapDTO | None: ...

    def report_message(self, *, data: ParleyReportData, now: datetime) -> bool: ...


class ParleyMembershipClaims(BaseModel):
    """Who is in a conversation, as Django sees it now; the Worker's member list."""

    model_config = ConfigDict(serialize_by_alias=True)

    iss: str
    aud: str
    conversation: str
    kind: ParleyConversationKind
    # Each member's id, state and whether they may write right now.
    members: list[dict[str, str | bool]]
    iat: int
    exp: int
    jti: str


class ParleyMemberSnapshot(BaseModel):
    user_id: int
    state: ParleyMemberState
    writable: bool


class ParleyConversationRepositoryProtocol(Protocol):
    @staticmethod
    def is_eligible(user_id: int) -> bool: ...

    @staticmethod
    def blocked_between(first_id: int, second_id: int) -> bool: ...

    @staticmethod
    def search_people(
        *, user_id: int, query: str, limit: int
    ) -> list[ParleyPersonDTO]: ...

    @staticmethod
    def find_direct(pair_key: str) -> int | None: ...

    @staticmethod
    def create_conversation(
        *,
        kind: ParleyConversationKind,
        title: str,
        created_by: int,
        pair_key: str | None,
    ) -> int: ...

    @staticmethod
    def set_member(
        *, conversation_id: int, user_id: int, state: ParleyMemberState, is_admin: bool
    ) -> None: ...

    @staticmethod
    def read_member(
        *, conversation_id: int, user_id: int
    ) -> tuple[ParleyConversationKind, ParleyMemberState, bool] | None: ...

    @staticmethod
    def count_active(conversation_id: int) -> int: ...

    @staticmethod
    def list_for(user_id: int) -> list[ParleyConversationDTO]: ...

    @staticmethod
    def read_for(
        *, conversation_id: int, user_id: int
    ) -> ParleyConversationDTO | None: ...

    @staticmethod
    def snapshot(
        conversation_id: int,
    ) -> tuple[ParleyConversationKind, list[ParleyMemberSnapshot]]: ...

    @staticmethod
    def conversation_ids_of(user_id: int) -> list[int]: ...

    @staticmethod
    def conversations_with(*, first_id: int, second_id: int) -> list[int]: ...

    @staticmethod
    def block(*, blocker_id: int, blocked_id: int) -> None: ...

    @staticmethod
    def unblock(*, blocker_id: int, blocked_id: int) -> None: ...


class ParleyMembershipOutboxProtocol(Protocol):
    # Sends the conversation's member list once the transaction commits.
    def schedule(self, *, conversation_ids: list[int]) -> None: ...


class ParleyConversationError(Exception):
    """A conversation change this person may not make; the code says which."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ParleyConversationServiceProtocol(Protocol):
    def list_for(self, user_id: int) -> list[ParleyConversationDTO]: ...

    def search_people(self, *, user_id: int, query: str) -> list[ParleyPersonDTO]: ...

    def start_direct(
        self, *, user_id: int, recipient_id: int
    ) -> ParleyConversationDTO: ...

    def accept(
        self, *, user_id: int, conversation_id: int
    ) -> ParleyConversationDTO: ...

    def decline(self, *, user_id: int, conversation_id: int) -> None: ...

    def leave(self, *, user_id: int, conversation_id: int) -> None: ...

    def create_group(
        self, *, user_id: int, title: str, member_ids: list[int]
    ) -> ParleyConversationDTO: ...

    def add_members(
        self, *, user_id: int, conversation_id: int, member_ids: list[int]
    ) -> ParleyConversationDTO: ...

    def remove_member(
        self, *, user_id: int, conversation_id: int, member_id: int
    ) -> None: ...

    def block(self, *, user_id: int, blocked_id: int) -> None: ...

    def unblock(self, *, user_id: int, blocked_id: int) -> None: ...
