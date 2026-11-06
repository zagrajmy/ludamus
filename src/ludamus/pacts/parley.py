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


class ParleyBootstrapDTO(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    sphere: dict[str, str]
    user: dict[str, str]
    rooms: list[ParleyRoomDTO]
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
    iat: int
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


class ParleyCapabilitySignerProtocol(Protocol):
    def sign(self, claims: ParleyCapabilityClaims) -> str: ...


class ParleyServiceProtocol(Protocol):
    def bootstrap(
        self, *, sphere_id: int, user_id: int, now: datetime
    ) -> ParleyBootstrapDTO | None: ...

    def report_message(self, *, data: ParleyReportData, now: datetime) -> bool: ...
