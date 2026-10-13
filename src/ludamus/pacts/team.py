"""Sphere team contracts: who runs a sphere, and the links that add to it.

A sphere's team is its `SphereMembership` rows — managers and comms people.
Managers grow it by sending invitation links: each one is single-use, carries
the role it grants, and expires. Opening one shows who invited you to what;
accepting it adds the membership and spends the link.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.multiverse import SphereRole


class AcceptInvitationOutcome(StrEnum):
    JOINED = "joined"
    # The link stays unspent, so it can still go to the person it was for.
    ALREADY_MEMBER = "already_member"
    # Unknown, expired, already used, revoked or another sphere's: one answer
    # for all, so a link reveals nothing about the invitations behind it.
    INVALID = "invalid"


class TeamMemberDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    name: str
    email: str | None
    role: SphereRole


class SphereInvitationDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    role: SphereRole
    token: str
    invited_by: str
    creation_time: datetime
    expires_at: datetime


class InvitationPreviewDTO(BaseModel):
    """What the person holding the link sees before accepting."""

    sphere_name: str
    role: SphereRole
    invited_by: str


class SphereInvitationCreateData(TypedDict):
    sphere_id: int
    role: SphereRole
    token: str
    created_by_id: int
    expires_at: datetime


class SphereTeamRepositoryProtocol(Protocol):
    @staticmethod
    def list_members(*, sphere_id: int) -> list[TeamMemberDTO]: ...
    @staticmethod
    def list_open_invitations(
        *, sphere_id: int, now: datetime
    ) -> list[SphereInvitationDTO]: ...
    @staticmethod
    def create_invitation(data: SphereInvitationCreateData) -> SphereInvitationDTO: ...
    @staticmethod
    def delete_open_invitation(*, sphere_id: int, pk: int, now: datetime) -> bool: ...
    @staticmethod
    def read_open_invitation(
        *, sphere_id: int, token: str, now: datetime
    ) -> InvitationPreviewDTO | None: ...
    @staticmethod
    def lock_open_invitation(
        *, sphere_id: int, token: str, now: datetime
    ) -> SphereInvitationDTO | None: ...
    @staticmethod
    def is_member(*, sphere_id: int, user_id: int) -> bool: ...
    @staticmethod
    def add_member(*, sphere_id: int, user_id: int, role: SphereRole) -> None: ...
    @staticmethod
    def mark_accepted(*, pk: int, user_id: int, now: datetime) -> None: ...


class SphereTeamServiceProtocol(Protocol):
    def list_members(self, *, sphere_id: int) -> list[TeamMemberDTO]: ...
    def list_open_invitations(self, *, sphere_id: int) -> list[SphereInvitationDTO]: ...
    def invite(
        self, *, sphere_id: int, role: SphereRole, invited_by_id: int
    ) -> SphereInvitationDTO: ...
    def revoke(self, *, sphere_id: int, pk: int) -> bool: ...
    def preview(self, *, sphere_id: int, token: str) -> InvitationPreviewDTO | None: ...
    def accept(
        self, *, sphere_id: int, token: str, user_id: int
    ) -> AcceptInvitationOutcome: ...
