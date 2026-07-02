"""Party subdomain contracts. See RFC 0001.

The drużyna: the group that enrolls together. DTOs and ports for party CRUD,
membership invites, and the companion (login-less member) lifecycle.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class PartyConsentMode(StrEnum):
    # How an enrollment reaches this member: taken-and-notified, or held until
    # they accept. A login-less companion is always ACCEPT_BY_DEFAULT; a real
    # user defaults to ACCEPT_INVITES and may grant the leader power of attorney.
    ACCEPT_BY_DEFAULT = "accept_by_default"
    ACCEPT_INVITES = "accept_invites"


class PartyMembershipStatus(StrEnum):
    ACTIVE = "active"
    INVITED = "invited"


class PartyMemberDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    membership_pk: int
    user_pk: int
    name: str
    slug: str
    is_login_less: bool
    is_leader: bool
    consent_mode: PartyConsentMode
    status: PartyMembershipStatus
    # Companions only: pending claim-link token, "" when none was issued.
    claim_token: str = ""


class PartyDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    name: str
    leader_pk: int
    leader_name: str
    # Viewer-relative: whether the requesting user leads this party.
    is_leader: bool
    # Viewer-relative: the viewer's first led party — the one that sponsors
    # their companions.
    is_default: bool
    members: list[PartyMemberDTO]


class PartyInviteDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    membership_pk: int
    party_pk: int
    party_name: str
    leader_name: str


class PartiesOverviewDTO(BaseModel):
    parties: list[PartyDTO]
    invites: list[PartyInviteDTO]


class InviteOutcome(StrEnum):
    INVITED = "invited"
    NO_SUCH_USER = "no_such_user"
    ALREADY_MEMBER = "already_member"


class DeletePartyOutcome(StrEnum):
    DELETED = "deleted"
    HAS_COMPANIONS = "has_companions"
    NOT_FOUND = "not_found"


class PartyInviteNotification(BaseModel):
    recipient_user_id: int
    recipient_email: str
    party_name: str
    leader_name: str


class InvitedUserDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    email: str


class LedPartyDTO(BaseModel):
    name: str
    leader_name: str


class PartyRepositoryProtocol(Protocol):
    @staticmethod
    def overview(viewer_pk: int) -> PartiesOverviewDTO: ...
    @staticmethod
    def create(*, leader_pk: int, name: str) -> int: ...
    @staticmethod
    def rename(*, leader_pk: int, party_pk: int, name: str) -> bool: ...
    @staticmethod
    def has_companions(*, leader_pk: int, party_pk: int) -> bool: ...
    @staticmethod
    def delete(*, leader_pk: int, party_pk: int) -> bool: ...
    @staticmethod
    def read_led_party(*, leader_pk: int, party_pk: int) -> LedPartyDTO | None: ...
    @staticmethod
    def find_invitable_user(email: str) -> InvitedUserDTO | None: ...
    @staticmethod
    def membership_exists(*, party_pk: int, user_pk: int) -> bool: ...
    @staticmethod
    def create_invited_membership(*, party_pk: int, user_pk: int) -> None: ...
    @staticmethod
    def accept_invite(*, membership_pk: int, user_pk: int) -> bool: ...
    @staticmethod
    def decline_invite(*, membership_pk: int, user_pk: int) -> bool: ...
    @staticmethod
    def remove_member(
        *, leader_pk: int, party_pk: int, membership_pk: int
    ) -> PartyMembershipStatus | None: ...
    @staticmethod
    def leave(*, user_pk: int, party_pk: int) -> bool: ...


class PartyNotifierProtocol(Protocol):
    def notify_party_invited(self, notification: PartyInviteNotification) -> None: ...


class PartyServiceProtocol(Protocol):
    def overview(self, viewer_pk: int) -> PartiesOverviewDTO: ...
    def create(self, *, leader_pk: int, name: str) -> int: ...
    def rename(self, *, leader_pk: int, party_pk: int, name: str) -> bool: ...
    def delete(self, *, leader_pk: int, party_pk: int) -> DeletePartyOutcome: ...
    def invite(self, *, leader_pk: int, party_pk: int, email: str) -> InviteOutcome: ...
    def accept_invite(self, *, user_pk: int, membership_pk: int) -> bool: ...
    def decline_invite(self, *, user_pk: int, membership_pk: int) -> bool: ...
    def remove_member(
        self, *, leader_pk: int, party_pk: int, membership_pk: int
    ) -> PartyMembershipStatus | None: ...
    def leave(self, *, user_pk: int, party_pk: int) -> bool: ...
