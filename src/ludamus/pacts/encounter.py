from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Protocol, TypedDict

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.calendar import CalendarReply, InviteMethod, PartStat
from ludamus.pacts.crowd import UserDTO

if TYPE_CHECKING:
    from ludamus.pacts.images import UploadedFileProtocol


# How far back the feed reads. Enforced twice — the repository stops
# fetching, the page stops rendering — so both halves cut at the same row.
PAST_FEED_LIMIT = 24


class EncountersPolicy(StrEnum):
    """Who may create encounters in a sphere. NONE turns the feature off."""

    NONE = "none"
    MANAGERS = "managers"
    EVERYONE = "everyone"


class EncounterDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    creation_time: datetime
    creator_id: int
    description: str
    end_time: datetime | None
    game: str
    is_public: bool = False
    max_participants: int
    pk: int
    place: str
    share_code: str
    sphere_id: int
    start_time: datetime
    title: str
    header_image_url: str = ""
    header_image_original_name: str = ""


class EncounterRSVPDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    creation_time: datetime
    encounter_id: int
    ip_address: str | None
    pk: int
    user_id: int


class EncounterData(TypedDict, total=False):
    creator_id: int
    description: str
    end_time: datetime | None
    game: str
    header_image: UploadedFileProtocol | str
    is_public: bool
    max_participants: int
    place: str
    share_code: str
    sphere_id: int
    start_time: datetime
    title: str


@dataclass
class EncounterIndexItem:
    encounter: EncounterDTO
    rsvp_count: int
    is_mine: bool
    organizer_name: str


@dataclass
class EncounterFeed:
    upcoming: list[EncounterIndexItem]
    past: list[EncounterIndexItem]


class EncounterRepositoryProtocol(Protocol):
    @staticmethod
    def create(data: EncounterData) -> EncounterDTO: ...
    @staticmethod
    def exists_for_sphere(sphere_id: int) -> bool: ...
    @staticmethod
    def read(pk: int, sphere_id: int) -> EncounterDTO: ...
    @staticmethod
    def read_by_share_code(share_code: str, sphere_id: int) -> EncounterDTO: ...
    @staticmethod
    def read_by_share_code_in_any_sphere(share_code: str) -> EncounterDTO: ...
    @staticmethod
    def list_visible_upcoming(
        sphere_id: int, user_id: int | None, *, limit: int | None = None
    ) -> list[EncounterDTO]: ...
    @staticmethod
    def list_visible_past(
        sphere_id: int, user_id: int | None, *, limit: int
    ) -> list[EncounterDTO]: ...
    @staticmethod
    def update(pk: int, data: EncounterData) -> None: ...
    @staticmethod
    def delete(pk: int) -> None: ...


class EncounterRSVPRepositoryProtocol(Protocol):
    @staticmethod
    def create(
        encounter_id: int, ip_address: str | None, user_id: int
    ) -> EncounterRSVPDTO: ...
    @staticmethod
    def list_by_encounter(encounter_id: int) -> list[EncounterRSVPDTO]: ...
    @staticmethod
    def count_by_encounter(encounter_id: int) -> int: ...
    @staticmethod
    def count_by_encounters(encounter_ids: list[int]) -> dict[int, int]: ...
    @staticmethod
    def recent_rsvp_exists(ip_address: str, seconds: int = 60) -> bool: ...
    @staticmethod
    def user_has_rsvpd(encounter_id: int, user_id: int) -> bool: ...
    @staticmethod
    def delete_by_user(encounter_id: int, user_id: int) -> None: ...


class InviteeStatus(StrEnum):
    INVITED = "invited"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    # NOTE: kept, not deleted, so the address still counts toward the
    # creator's daily invite limit.
    REMOVED = "removed"


class InviteLimitError(Exception):
    """The creator has invited as many new addresses as a day allows."""


class EncounterInviteeDTO(BaseModel):
    """Someone the organizer invited by email, account or not.

    `user_id` is the account with that email, when one exists.
    """

    model_config = ConfigDict(from_attributes=True)

    email: str
    status: InviteeStatus
    user_id: int | None = None


class EncounterDetailContextDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    encounter: EncounterDTO
    creator: UserDTO
    attendees: list[UserDTO]
    rsvp_count: int
    is_creator: bool
    user_has_rsvpd: bool
    # NOTE: filled for the creator alone; invitees' addresses are not for
    # other guests to see.
    invitees: list[EncounterInviteeDTO] = []
    # Invitees without an account who accepted from their calendar: coming,
    # though not in `attendees`.
    accepted_guest_count: int = 0

    # Derived from the capacity and the signup count rather than stored, so
    # the two can't drift apart.
    @property
    def spots_remaining(self) -> int | None:
        limit = self.encounter.max_participants
        taken = self.rsvp_count + self.accepted_guest_count
        return max(0, limit - taken) if limit > 0 else None

    @property
    def is_full(self) -> bool:
        return self.spots_remaining == 0


class EncounterInviteReason(StrEnum):
    CREATED = auto()
    INVITED = auto()
    JOINED = auto()
    CHANGED = auto()
    LEFT = auto()
    UNINVITED = auto()
    DELETED = auto()
    FULL = auto()


class EncounterInviteeRepositoryProtocol(Protocol):
    @staticmethod
    def list_by_encounter(encounter_id: int) -> list[EncounterInviteeDTO]:
        """Invitees on the list now; removed ones are left out."""

    @staticmethod
    def add(*, encounter_id: int, emails: list[str], creator_id: int) -> None:
        """Invite `emails`; a removed invitee among them is invited again."""

    @staticmethod
    def remove(encounter_id: int, emails: list[str]) -> None: ...
    @staticmethod
    def set_status(*, encounter_id: int, email: str, status: InviteeStatus) -> bool: ...
    @staticmethod
    def read_status(encounter_id: int, email: str) -> InviteeStatus | None: ...
    @staticmethod
    def count_accepted_without_signup(encounter_id: int) -> int: ...
    @staticmethod
    def emails_invited_by_creator_since(
        creator_id: int, since: datetime
    ) -> set[str]: ...


class EncounterInvite(BaseModel):
    """A calendar invite for one attendee, mailed so it lands in their calendar.

    `end_time` is always set: an invite without one shows as a zero-length
    event, so the mill fills in the default length.
    """

    reason: EncounterInviteReason
    method: InviteMethod
    partstat: PartStat
    asks_reply: bool
    uid: str
    sequence: int
    encounter: EncounterDTO
    end_time: datetime
    organizer_name: str
    attendee_name: str
    attendee_email: str
    sphere_domain: str


class EncounterInviteMailerProtocol(Protocol):
    def send(self, invites: list[EncounterInvite]) -> None: ...


class ReplyAddressProtocol(Protocol):
    """Proves a calendar reply answers an invite we mailed to that attendee.

    Each invite names a per-attendee organizer address; a reply arriving at
    any other address is forged or misrouted.
    """

    def matches(self, *, address: str, uid: str, attendee_email: str) -> bool: ...


class ReplyOutcome(StrEnum):
    ACCEPTED = auto()
    DECLINED = auto()
    FULL = auto()
    IGNORED = auto()
    FORGED = auto()


class RSVPOutcome(StrEnum):
    CREATED = auto()
    FULL = auto()
    THROTTLED = auto()
    ALREADY_SIGNED_UP = auto()


class EncounterServiceProtocol(Protocol):
    def enabled(self, sphere_id: int) -> bool: ...
    def list_feed(self, *, sphere_id: int, user_id: int | None) -> EncounterFeed: ...
    def list_upcoming(
        self, *, sphere_id: int, user_id: int | None, limit: int
    ) -> list[EncounterIndexItem]: ...
    def can_create(self, *, sphere_id: int, user_id: int) -> bool: ...
    def build_detail(
        self, *, share_code: str, sphere_id: int, current_user_id: int | None
    ) -> EncounterDetailContextDTO: ...
    def read_by_share_code(
        self, *, share_code: str, sphere_id: int
    ) -> EncounterDTO: ...
    def create(
        self, data: EncounterData, *, invitee_emails: list[str]
    ) -> EncounterDTO: ...
    def read_owned(self, *, pk: int, sphere_id: int, user_id: int) -> EncounterDTO: ...
    def list_owned_invitees(
        self, *, pk: int, sphere_id: int, user_id: int
    ) -> list[EncounterInviteeDTO]: ...
    def update_owned(
        self,
        *,
        pk: int,
        sphere_id: int,
        user_id: int,
        data: EncounterData,
        invitee_emails: list[str],
    ) -> EncounterDTO: ...
    def delete_owned(self, *, pk: int, sphere_id: int, user_id: int) -> None: ...
    def rsvp(
        self, *, share_code: str, sphere_id: int, user_id: int, ip_address: str
    ) -> RSVPOutcome: ...
    def cancel_rsvp(self, *, share_code: str, sphere_id: int, user_id: int) -> None: ...


class EncounterReplyServiceProtocol(Protocol):
    def apply_calendar_reply(
        self, *, address: str, reply: CalendarReply
    ) -> ReplyOutcome: ...
