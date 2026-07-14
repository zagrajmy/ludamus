"""Party subdomain contracts. See RFC 0001.

The drużyna: the group that enrolls together. DTOs and ports for party CRUD,
membership invites, consent, and the companion (login-less member) lifecycle.
"""

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.crowd import CompanionDTO

# Form/query value for enrolling without a party ("Just myself").
ENROLL_WITHOUT_PARTY = "none"


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
    full_name: str
    username: str
    slug: str
    is_login_less: bool
    is_leader: bool
    consent_mode: PartyConsentMode
    status: PartyMembershipStatus
    # Companions only: pending claim-link token, "" when none was issued.
    claim_token: str = ""
    avatar_url: str = ""


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
    created_at: datetime
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


class EnrollmentPartyChoiceDTO(BaseModel):
    # A selector pill on the enroll page. The label is derived in the template
    # from the structured fields (name, else "Your party" for the viewer's own
    # unnamed led party, else the leader's name) so translations stay in gates.
    pk: int
    name: str
    leader_name: str
    is_own_led: bool


class EnrollmentPartyMemberDTO(BaseModel):
    # Enroll-page slice of a membership — deliberately without the companion
    # claim token (a bearer credential that must not reach this context).
    user_pk: int
    name: str
    slug: str
    is_login_less: bool
    is_leader: bool
    consent_mode: PartyConsentMode
    status: PartyMembershipStatus


class SelectedEnrollmentPartyDTO(BaseModel):
    pk: int
    name: str
    leader_name: str
    is_own_led: bool
    members: list[EnrollmentPartyMemberDTO]


class EnrollmentPartiesDTO(BaseModel):
    # "Just myself" is the implicit extra choice whenever `choices` is
    # non-empty; it maps to `selected is None`.
    choices: list[EnrollmentPartyChoiceDTO]
    selected: SelectedEnrollmentPartyDTO | None = None
    # The viewer's login-less companions in the selected party; only their own
    # led party can seat companions, so this is empty otherwise.
    companions: list[CompanionDTO] = []
    # The requested party is not one of the viewer's — the caller must surface
    # an error instead of silently substituting a default.
    requested_invalid: bool = False


class InviteOutcome(StrEnum):
    INVITED = "invited"
    NO_SUCH_USER = "no_such_user"
    ALREADY_MEMBER = "already_member"
    AMBIGUOUS_HANDLE = "ambiguous_handle"


class CompanionAddOutcome(StrEnum):
    ADDED = "added"
    NO_SUCH_COMPANION = "no_such_companion"
    ALREADY_MEMBER = "already_member"
    AMBIGUOUS_NAME = "ambiguous_name"


class DeletePartyOutcome(StrEnum):
    DELETED = "deleted"
    HAS_COMPANIONS = "has_companions"
    NOT_FOUND = "not_found"


class PartyInviteNotification(BaseModel):
    recipient_user_id: int
    recipient_email: str
    party_name: str
    leader_name: str


class PartyEnrolledNotification(BaseModel):
    recipient_user_id: int
    recipient_email: str
    actor_name: str
    session_id: int
    session_title: str
    event_slug: str


class HeldSeatNotification(BaseModel):
    recipient_user_id: int
    recipient_email: str
    actor_name: str
    session_id: int
    session_title: str
    claim_token: str
    offer_expires_at: datetime


class InvitedUserDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    email: str


class InvitablePartyDTO(BaseModel):
    pk: int
    name: str
    leader_name: str
    already_member: bool


class PartyJoinResult(BaseModel):
    party_pk: int
    joined: bool


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
    def find_invitable_users(identifier: str) -> list[InvitedUserDTO]: ...
    @staticmethod
    def set_invite_token(*, leader_pk: int, party_pk: int, token: str) -> bool: ...
    @staticmethod
    def read_invite_token(*, leader_pk: int, party_pk: int) -> str: ...
    @staticmethod
    def read_party_by_invite_token(
        *, token: str, viewer_pk: int
    ) -> InvitablePartyDTO | None: ...
    @staticmethod
    def join_via_token(*, token: str, user_pk: int) -> PartyJoinResult | None: ...
    @staticmethod
    def can_view(*, party_pk: int, viewer_pk: int) -> bool: ...
    @staticmethod
    def membership_exists(*, party_pk: int, user_pk: int) -> bool: ...
    @staticmethod
    def create_invited_membership(
        *,
        party_pk: int,
        user_pk: int,
        consent_mode: PartyConsentMode = PartyConsentMode.ACCEPT_INVITES,
        status: PartyMembershipStatus = PartyMembershipStatus.INVITED,
    ) -> None: ...
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
    @staticmethod
    def led_party_companions(
        *, leader_pk: int, party_pk: int | None
    ) -> list[CompanionDTO]: ...
    @staticmethod
    def set_consent(*, user_pk: int, party_pk: int, mode: PartyConsentMode) -> bool: ...


class PartyNotifierProtocol(Protocol):
    def notify_party_invited(self, notification: PartyInviteNotification) -> None: ...
    def notify_party_enrolled(
        self, notification: PartyEnrolledNotification
    ) -> None: ...


class PartyServiceProtocol(Protocol):
    def overview(self, viewer_pk: int) -> PartiesOverviewDTO: ...
    def create(self, *, leader_pk: int, name: str) -> int: ...
    def rename(self, *, leader_pk: int, party_pk: int, name: str) -> bool: ...
    def delete(self, *, leader_pk: int, party_pk: int) -> DeletePartyOutcome: ...
    def invite(
        self, *, leader_pk: int, party_pk: int, identifier: str
    ) -> InviteOutcome: ...
    def add_companion(
        self, *, leader_pk: int, party_pk: int, display_name: str
    ) -> CompanionAddOutcome: ...
    def reset_invite_link(self, *, leader_pk: int, party_pk: int) -> str | None: ...
    def read_invite_token(self, *, leader_pk: int, party_pk: int) -> str: ...
    def read_invitable_party(
        self, *, token: str, viewer_pk: int
    ) -> InvitablePartyDTO | None: ...
    def join_via_link(self, *, token: str, user_pk: int) -> PartyJoinResult | None: ...
    def accept_invite(self, *, user_pk: int, membership_pk: int) -> bool: ...
    def decline_invite(self, *, user_pk: int, membership_pk: int) -> bool: ...
    def remove_member(
        self, *, leader_pk: int, party_pk: int, membership_pk: int
    ) -> PartyMembershipStatus | None: ...
    def leave(self, *, user_pk: int, party_pk: int) -> bool: ...
    def enrollment_selection(
        self, *, viewer_pk: int, requested_party: str | None
    ) -> EnrollmentPartiesDTO: ...
    def set_my_consent(
        self, *, user_pk: int, party_pk: int, mode: PartyConsentMode
    ) -> bool: ...
    def announce_member_enrolled(
        self, notification: PartyEnrolledNotification
    ) -> None: ...
