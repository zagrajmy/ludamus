from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ludamus.pacts.sphere import SphereRole
from ludamus.pacts.user import AgeBand

if TYPE_CHECKING:
    from collections.abc import Mapping


class ParleyRoomKind(StrEnum):
    # A sphere's managers, among themselves.
    ORGANIZERS = "organizers"
    EVENT = "event"
    SESSION = "session"


class ParleyRoomDTO(BaseModel):
    kind: ParleyRoomKind
    sphere_id: int = Field(serialization_alias="sphere")
    # The event's or the programme point's; the organizers' room has none.
    pk: int | None = Field(default=None, exclude=True)
    # The event a programme point belongs to.
    event_pk: int | None = Field(default=None, exclude=True)
    title: str
    can_write: bool = Field(serialization_alias="canWrite")
    can_moderate: bool = Field(default=False, serialization_alias="canModerate")
    # When the event the room belongs to ends and starts; the organizers'
    # room has neither.
    ends_at: int | None = Field(default=None, exclude=True)
    starts_at: int | None = Field(default=None, exclude=True)
    # "<kind>:<name>", as the Worker and the browser know the room.
    id: str = ""

    @property
    def name(self) -> str:
        """The room's id without its kind: its sphere, then its own pk."""
        return str(self.sphere_id) if self.pk is None else f"{self.sphere_id}:{self.pk}"

    @model_validator(mode="after")
    def _named(self) -> Self:
        self.id = f"{self.kind}:{self.name}"
        return self


class ParleyAccessDTO(BaseModel):
    user_id: int
    user_name: str
    user_avatar_url: str
    # Every room of every sphere with chat on that this person is in.
    rooms: list[ParleyRoomDTO]


class ParleyAgeGate(StrEnum):
    """Why direct messages stay shut to someone, when their age is the reason."""

    UNCONFIRMED = "unconfirmed"
    UNDER_16 = "under_16"


class ParleyConversationKind(StrEnum):
    DIRECT = "direct"
    GROUP = "group"
    # A party's own, its members kept in step with the party's.
    PARTY = "party"
    # A staff case's thread, its members kept in step with who is staff.
    STAFF = "staff"


class ParleyConversationPolicy(BaseModel):
    """What a kind of conversation is: who may be in it, and who decides."""

    model_config = ConfigDict(frozen=True)

    # Open only to people direct messages are open to: 16 and over.
    needs_direct: bool
    # People join, leave and rename it themselves; otherwise its party does.
    self_managed: bool
    # Between two people: it ends when either leaves or blocks the other,
    # and it goes by the other person's name.
    one_to_one: bool
    # Two people in it are a direct message by another name, so two talk
    # only when direct messages are open to both.
    pair_needs_direct: bool
    # Only staff (`is_staff`) are let in, and its messages are moderation
    # records: a staff case's thread.
    staff_only: bool


CONVERSATION_POLICIES: Mapping[ParleyConversationKind, ParleyConversationPolicy] = (
    MappingProxyType(
        {
            ParleyConversationKind.DIRECT: ParleyConversationPolicy(
                needs_direct=True,
                self_managed=True,
                one_to_one=True,
                pair_needs_direct=False,
                staff_only=False,
            ),
            ParleyConversationKind.GROUP: ParleyConversationPolicy(
                needs_direct=True,
                self_managed=True,
                one_to_one=False,
                pair_needs_direct=False,
                staff_only=False,
            ),
            ParleyConversationKind.PARTY: ParleyConversationPolicy(
                needs_direct=False,
                self_managed=False,
                one_to_one=False,
                pair_needs_direct=True,
                staff_only=False,
            ),
            ParleyConversationKind.STAFF: ParleyConversationPolicy(
                needs_direct=False,
                self_managed=False,
                one_to_one=False,
                pair_needs_direct=False,
                staff_only=True,
            ),
        }
    )
)


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
    # What the conversation is called: its name, or else the other person
    # (direct) or the other members (group).
    title: str
    # The name its members gave it; empty when they gave none.
    name: str = ""
    state: ParleyMemberState
    can_write: bool = Field(serialization_alias="canWrite")
    is_admin: bool = Field(serialization_alias="isAdmin")
    members: list[ParleyPersonDTO]


class ParleyBootstrapDTO(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    user: dict[str, str]
    rooms: list[ParleyRoomDTO]
    # Whether direct messages and groups are open to this person at all.
    can_message: bool = Field(default=False, serialization_alias="canMessage")
    age_gate: ParleyAgeGate | None = Field(default=None, serialization_alias="ageGate")
    conversations: list[ParleyConversationDTO] = Field(default_factory=list)
    # People this person has blocked: their messages stay out of sight.
    blocked: list[ParleyPersonDTO] = Field(default_factory=list)
    capability_token: str = Field(serialization_alias="capabilityToken")
    agent_host: str = Field(serialization_alias="agentHost")


class ParleyManagedSphere(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    organizers: bool


class ParleyEventGrant(BaseModel):
    """One event's rooms on a pass: its chat and its programme points."""

    model_config = ConfigDict(serialize_by_alias=True)

    ends_at: int = Field(serialization_alias="endsAt")
    # Whether the event still takes messages.
    writable: bool
    # Whether its own chat is open to this person.
    chat: bool
    # Its programme points this person is in, by pk, and whether each still
    # takes messages; they end with the event.
    sessions: dict[str, bool]


class ParleyCapabilityClaims(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    iss: str
    aud: str
    sub: str
    name: str
    avatar: str
    # Spheres whose every room this person moderates, so a manager's token
    # stays the same size however many rooms their sphere has; each says
    # whether its organizers' room is open.
    managed: dict[str, ParleyManagedSphere]
    # Their own events and programme points in spheres they do not
    # manage, each event by "<sphere>:<pk>".
    events: dict[str, ParleyEventGrant]
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
    user_id: int
    room_id: str
    message_id: int = Field(gt=0)
    reason: str = Field(max_length=255)


class ParleyReportedMessage(BaseModel):
    """A reported message as its room keeps it, deleted words included."""

    author_id: str
    author_name: str
    body: str
    created_at: datetime
    deleted_at: datetime | None


class ParleyReportRecord(BaseModel):
    reporter_id: int
    # A report belongs to the sphere whose room it came from, or to the
    # conversation it came from; never both.
    sphere_id: int | None
    conversation_id: int | None
    room_id: str
    message_id: int
    reason: str
    # What the room said the message was; None when the Worker could not say.
    message: ParleyReportedMessage | None


class ParleyMessageLookupClaims(BaseModel):
    """Django asking a room for one message, to keep a copy with a report."""

    iss: str
    aud: str
    room: str
    message: int
    iat: int
    exp: int
    jti: str


class ParleyWorkerUnavailableError(Exception):
    """The chat Worker could not be asked, or did not answer."""


class ParleyMessageReaderProtocol(Protocol):
    # None when the room has no such message; raises
    # ParleyWorkerUnavailableError when it cannot be asked.
    def read_message(self, token: str, /) -> ParleyReportedMessage | None: ...

    # Deletes the message for everyone in its room, a message the room no
    # longer has included; raises ParleyWorkerUnavailableError when the room
    # cannot be told.
    def moderate(self, token: str, /) -> None: ...


class ParleyReportedRef(BaseModel):
    room_id: str
    message_id: int


class ParleyModerationResult(BaseModel):
    deleted: int
    failed: int


class ParleyTimeWindow(BaseModel):
    now: datetime
    retained_after: datetime
    writable_after: datetime


class ParleyRepositoryProtocol(Protocol):
    # `moderated` are the spheres whose every room this person moderates.
    @staticmethod
    def read_access(
        *, user_id: int, window: ParleyTimeWindow, moderated: frozenset[int]
    ) -> ParleyAccessDTO | None: ...

    @staticmethod
    def has_rooms(
        *, user_id: int, window: ParleyTimeWindow, moderated: frozenset[int]
    ) -> bool: ...

    # The spheres with chat on whose team this person is on.
    @staticmethod
    def list_team_seats(user_id: int) -> list[ParleyTeamSeat]: ...

    @staticmethod
    def save_report(report: ParleyReportRecord) -> None: ...

    # The messages these reports are about, each once.
    @staticmethod
    def list_reported(report_ids: list[int]) -> list[ParleyReportedRef]: ...

    # Marks every open report of the message resolved.
    @staticmethod
    def resolve_reports(*, room_id: str, message_id: int, now: datetime) -> None: ...

    # Empties the words reports copied of messages written at or before the
    # cutoff, keeping each report; returns how many it emptied.
    @staticmethod
    def forget_copies_written_before(cutoff: datetime) -> int: ...

    @staticmethod
    def read_event_sphere_id(event_id: int) -> int | None: ...

    @staticmethod
    def list_chat_sphere_ids() -> list[int]: ...


class ParleySignerProtocol(Protocol):
    def sign(
        self,
        claims: (
            ParleyCapabilityClaims
            | ParleyMembershipClaims
            | ParleyMessageLookupClaims
            | ParleyRevocationClaims
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

    def revoke_event(self, *, event_id: int) -> None: ...

    def age_changed(self, *, user_id: int) -> None: ...


class ParleyServiceProtocol(Protocol):
    def bootstrap(
        self, *, user_id: int, now: datetime
    ) -> ParleyBootstrapDTO | None: ...

    def is_open_to(self, *, user_id: int, now: datetime) -> bool: ...

    def report_message(self, *, data: ParleyReportData, now: datetime) -> bool: ...

    def delete_reported(
        self, *, report_ids: list[int], now: datetime
    ) -> ParleyModerationResult: ...


class ParleyMembershipClaims(BaseModel):
    """Who is in a conversation, as Django sees it now; the Worker's member list."""

    model_config = ConfigDict(serialize_by_alias=True)

    iss: str
    aud: str
    conversation: str
    kind: ParleyConversationKind
    # Whether only people direct messages are open to may be in it.
    needs_direct: bool = Field(serialization_alias="needsDirect")
    # How long the room keeps each message, in seconds.
    retain_for: int = Field(serialization_alias="retainFor")
    # Each member's id, state and whether they may write right now.
    members: list[dict[str, str | bool]]
    iat: int
    exp: int
    jti: str


class ParleyMemberSnapshot(BaseModel):
    user_id: int
    state: ParleyMemberState
    writable: bool
    age_band: AgeBand
    signs_in: bool
    is_staff: bool


class ParleyMembership(BaseModel):
    """Someone's place in a conversation."""

    kind: ParleyConversationKind
    state: ParleyMemberState
    is_admin: bool


class ParleyTeamSeat(BaseModel):
    """A sphere someone is on the team of, and in what role."""

    sphere_id: int
    role: SphereRole


class ParleyPartyCandidate(BaseModel):
    """An active member of a party who can sign in, and the age they confirmed."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    age_band: AgeBand


class ParleyConversationRepositoryProtocol(Protocol):
    @staticmethod
    def is_eligible(user_id: int) -> bool: ...

    @staticmethod
    def read_age_band(user_id: int) -> AgeBand: ...

    @staticmethod
    def exists(user_id: int) -> bool: ...

    @staticmethod
    def list_blocked(user_id: int) -> list[ParleyPersonDTO]: ...

    @staticmethod
    def blocked_between(first_id: int, second_id: int) -> bool: ...

    @staticmethod
    def search_people(
        *, user_id: int, query: str, limit: int
    ) -> list[ParleyPersonDTO]: ...

    @staticmethod
    def find_direct(pair_key: str) -> int | None: ...

    @staticmethod
    def find_group(member_ids: list[int]) -> int | None: ...

    @staticmethod
    def set_title(*, conversation_id: int, title: str) -> None: ...

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
    ) -> ParleyMembership | None: ...

    @staticmethod
    def count_active(conversation_id: int) -> int: ...

    @staticmethod
    def list_for(user_id: int) -> list[ParleyConversationDTO]: ...

    @staticmethod
    def read_for(
        *, conversation_id: int, user_id: int
    ) -> ParleyConversationDTO | None: ...

    # Everyone still in the conversation, as the Worker may be told of them.
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

    @staticmethod
    def list_party_candidates(party_id: int) -> list[ParleyPartyCandidate]: ...

    # Makes these people, and no one else, the party chat's members, opening
    # the chat if it has none yet; the chat's id when who is in it changed,
    # else None.
    @staticmethod
    def set_party_members(*, party_id: int, user_ids: list[int]) -> int | None: ...

    # The parties this person is in, or whose chat they are in.
    @staticmethod
    def party_ids_of(user_id: int) -> list[int]: ...

    # Every party, and every party a chat was kept for after it was gone.
    @staticmethod
    def list_party_ids() -> list[int]: ...

    @staticmethod
    def list_party_chat_ids() -> list[int]: ...

    # Holds the party until the transaction ends, so its chat is synced by
    # one change at a time.
    @staticmethod
    def lock_party(party_id: int) -> None: ...

    @staticmethod
    def has_conversation(
        *, user_id: int, kinds: frozenset[ParleyConversationKind]
    ) -> bool: ...


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

    def rename(
        self, *, user_id: int, conversation_id: int, name: str
    ) -> ParleyConversationDTO: ...

    def block(self, *, user_id: int, blocked_id: int) -> None: ...

    def unblock(self, *, user_id: int, blocked_id: int) -> None: ...


class ParleyPartyChatProtocol(Protocol):
    """Keeps a party's chat in step with who is in the party."""

    def sync_party(self, party_id: int) -> None: ...

    def sync_parties_of(self, user_id: int) -> None: ...

    def parties_of(self, user_id: int) -> list[int]: ...

    def open_existing_chats(self) -> int: ...
