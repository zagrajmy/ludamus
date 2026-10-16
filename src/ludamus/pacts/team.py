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

INVITATION_NOTE_MAX_LENGTH = 100


class AcceptInvitationOutcome(StrEnum):
    JOINED = "joined"
    # Checked before the link itself: a member re-opening their own spent
    # link is told they are in, not that the link is dead.
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
    """An invitation as the panel lists it: never with its link.

    Only the token's hash is stored, so the link exists once, when it is
    issued (`IssuedInvitationDTO`).
    """

    model_config = ConfigDict(from_attributes=True)

    pk: int
    role: SphereRole
    note: str
    invited_by: str
    creation_time: datetime
    expires_at: datetime


class IssuedInvitationDTO(BaseModel):
    invitation: SphereInvitationDTO
    token: str


class InvitationPreviewDTO(BaseModel):
    """What the person holding the link is offered."""

    role: SphereRole
    invited_by: str


class JoinPageDTO(BaseModel):
    """The join page's whole state: what the link offers and who is asking.

    `invitation` is None when the link no longer works; `member_role` is set
    when the viewer is already on the team, whatever the link's state.
    """

    sphere_name: str
    invitation: InvitationPreviewDTO | None
    member_role: SphereRole | None


class SphereInvitationCreateData(TypedDict):
    sphere_id: int
    role: SphereRole
    token_hash: str
    note: str
    created_by_id: int
    expires_at: datetime


class InvitationRotationData(TypedDict):
    # A fresh link for an open invitation: its role and note stay, the token,
    # the issuer and the week it lives for are new.
    token_hash: str
    created_by_id: int
    creation_time: datetime
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
    def rotate_open_invitation(
        *, sphere_id: int, pk: int, rotation: InvitationRotationData, now: datetime
    ) -> SphereInvitationDTO | None: ...
    @staticmethod
    def read_sphere_name(*, sphere_id: int) -> str: ...
    @staticmethod
    def read_open_invitation(
        *, sphere_id: int, token_hash: str, now: datetime
    ) -> InvitationPreviewDTO | None: ...
    @staticmethod
    def lock_open_invitation(
        *, sphere_id: int, token_hash: str, now: datetime
    ) -> SphereInvitationDTO | None: ...
    @staticmethod
    def read_member_role(*, sphere_id: int, user_id: int) -> SphereRole | None: ...
    @staticmethod
    def add_member(*, sphere_id: int, user_id: int, role: SphereRole) -> bool: ...
    @staticmethod
    def mark_accepted(*, pk: int, user_id: int, now: datetime) -> None: ...


class SphereTeamServiceProtocol(Protocol):
    def list_members(self, *, sphere_id: int) -> list[TeamMemberDTO]: ...
    def list_open_invitations(self, *, sphere_id: int) -> list[SphereInvitationDTO]: ...
    def invite(
        self, *, sphere_id: int, role: SphereRole, note: str, invited_by_id: int
    ) -> IssuedInvitationDTO: ...
    def revoke(self, *, sphere_id: int, pk: int) -> bool: ...
    def reissue(
        self, *, sphere_id: int, pk: int, reissued_by_id: int
    ) -> IssuedInvitationDTO | None: ...
    def join_page(
        self, *, sphere_id: int, token: str, viewer_id: int | None
    ) -> JoinPageDTO: ...
    def accept(
        self, *, sphere_id: int, token: str, user_id: int
    ) -> AcceptInvitationOutcome: ...
