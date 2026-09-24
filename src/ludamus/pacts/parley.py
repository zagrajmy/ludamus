from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ParleyRoomKind(StrEnum):
    SPHERE = "sphere"
    SESSION = "session"


class ParleyRoomDTO(BaseModel):
    id: str
    kind: ParleyRoomKind
    title: str
    can_write: bool = Field(serialization_alias="canWrite")
    can_moderate: bool = Field(default=False, serialization_alias="canModerate")
    read_only_at: int | None = Field(default=None, exclude=True)
    delete_at: int | None = Field(default=None, exclude=True)


class ParleyAccessDTO(BaseModel):
    sphere_id: int
    sphere_name: str
    user_id: int
    user_name: str
    user_avatar_url: str
    rooms: list[ParleyRoomDTO]
    moderated_room_ids: list[str]


class ParleyBootstrapDTO(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    sphere: dict[str, str]
    user: dict[str, str]
    rooms: list[ParleyRoomDTO]
    capability_token: str = Field(serialization_alias="capabilityToken")
    agent_host: str = Field(serialization_alias="agentHost")


class ParleyCapabilityClaims(BaseModel):
    iss: str
    aud: str
    sub: str
    sphere: str
    name: str
    avatar: str
    rooms: list[str]
    writes: list[str]
    moderates: list[str]
    lifecycle: dict[str, dict[str, int]]
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
    read_only_delay: timedelta
    retention: timedelta


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
