"""Contracts for a member enrolling themselves and the people they act for.

The enroll page reads one `MemberEnrollPageDTO`, posts back what its form
parsed as a `MemberEnrollSubmission`, and gets a `MemberEnrollOutcome`. The
service decides every seat through `SeatDesk` (mills/enrollment_seats.py), the
path anonymous enrollment takes too. Codes, not sentences: the gate words them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

from ludamus.pacts.chronology import SessionCardStatsDTO
from ludamus.pacts.crowd import UserDTO
from ludamus.pacts.enrollment import EnrollmentWindowSnapshot, SeatRepositoryProtocol
from ludamus.pacts.legacy import EventDTO

if TYPE_CHECKING:
    from ludamus.pacts.legacy import VirtualEnrollmentConfig
    from ludamus.pacts.party import EnrollmentPartiesDTO

# The guests stepper's upper bound: the form offers no more, the page says so.
MAX_GUESTS = 10
# What a ticked "Include" box posts on the full page (desired-state mode); the
# one-click fragment on the event page posts an EnrollmentChoice instead.
INCLUDE_VALUE = "include"


class EnrollmentChoice(StrEnum):
    """What a per-person enroll field posts: the values its choices carry."""

    CANCEL = auto()
    ENROLL = auto()
    WAITLIST = auto()


@dataclass(frozen=True)
class PartyMemberFlags:
    is_member: bool = False
    needs_accept: bool = False
    blocked: bool = False


@dataclass
class SessionUserParticipationData:
    user: UserDTO
    user_enrolled: bool = False
    user_waiting: bool = False
    seat_held: bool = False
    offer_pending: bool = False
    has_time_conflict: bool = False
    membership: PartyMemberFlags = PartyMemberFlags()


class EnrollOptionLabel(StrEnum):
    NO_CHANGE = auto()
    NO_CHANGE_CONFLICT = auto()
    CANCEL_ENROLLMENT = auto()
    MOVE_TO_WAITLIST = auto()
    ENROLL_IF_SPOTS = auto()
    DECLINE_OFFER = auto()
    ENROLL = auto()
    JOIN_WAITLIST = auto()
    NO_OPTIONS_EMAIL = auto()
    NO_OPTIONS_ACCESS = auto()
    WITHDRAW_HELD_SEAT = auto()
    HOLD_SEAT = auto()


class EnrollHelp(StrEnum):
    NONE = ""
    TIME_CONFLICT = auto()
    EMAIL_REQUIRED = auto()
    ACCESS_REQUIRED = auto()
    NO_OPTIONS = auto()
    WITHDRAW_RELEASES = auto()
    OWN_ENROLLMENT = auto()
    RELEASED_IF_UNCLAIMED = auto()


@dataclass(frozen=True)
class EnrollOption:
    # "" is "no change"; anything else is an EnrollmentChoice.
    value: str
    label: EnrollOptionLabel


@dataclass(frozen=True)
class EnrollField:
    """One person's row: the moves the viewer may make for them."""

    user: UserDTO
    options: tuple[EnrollOption, ...]
    help: EnrollHelp = EnrollHelp.NONE

    @property
    def choices(self) -> frozenset[EnrollmentChoice]:
        return frozenset(
            EnrollmentChoice(option.value) for option in self.options if option.value
        )


class EnrollRefusal(StrEnum):
    """Why a posted "enroll" the page did not offer is refused."""

    EMAIL_REQUIRED = auto()
    ACCESS_REQUIRED = auto()
    NOT_AVAILABLE = auto()


class AccessProblem(StrEnum):
    """What a restricted session wants from a viewer whose submit failed."""

    EMAIL = auto()
    ACCESS = auto()


@dataclass(frozen=True)
class RosterMember:
    # One person the viewer can act for on the enroll screen.
    user: UserDTO
    # ACCEPT_INVITES member: "enroll" holds an OFFERED seat they must claim.
    needs_accept: bool = False
    # On a restricted event a member's seat spends that member's own
    # allowance, so a member without slots gets no enroll/hold choice.
    can_enroll: bool = True


class EnrollAgendaDTO(BaseModel):
    start_time: datetime
    end_time: datetime
    # The room as its path reads: "Building > Floor > Room".
    space: str


class EnrollSessionDTO(BaseModel):
    pk: int
    title: str
    cover_image_url: str
    facilitator_name: str
    description: str
    min_age: int
    participants_limit: int
    presenter_id: int | None
    presenter: UserDTO | None
    # None while the session is not on the timetable.
    agenda_item: EnrollAgendaDTO | None
    is_publicly_scheduled: bool
    event: EventDTO
    seats: SessionCardStatsDTO
    eligible_windows: list[EnrollmentWindowSnapshot]


@dataclass(frozen=True)
class MemberEnrollQuery:
    event_slug: str
    session_id: int
    sphere_id: int
    viewer_id: int
    viewer_slug: str
    requested_party: str | None


@dataclass(frozen=True)
class MemberEnrollPageDTO:
    """Everything one request decides from, read once before the form."""

    session: EnrollSessionDTO
    viewer: UserDTO
    parties: EnrollmentPartiesDTO
    # The viewer, then their companions, then the selected party's members.
    household: tuple[RosterMember, ...]
    fields: tuple[EnrollField, ...]
    user_data: tuple[SessionUserParticipationData, ...]
    # +N headcount guests; None when no open window takes anonymous seats.
    guest_count: int | None
    # Each household member's row on the session, as the form saw it.
    statuses: dict[int, str]
    # Household members holding a seat in an overlapping session.
    conflicted_ids: frozenset[int]
    # The passes a submit spends; None when the seating window asks for none.
    slot_allowance: VirtualEnrollmentConfig | None
    # Whether the viewer's passes admit them to restricted windows.
    actor_configured: bool
    enroll_refusal: EnrollRefusal | None
    access_problem: AccessProblem | None

    @property
    def party_id(self) -> int | None:
        return self.parties.selected.pk if self.parties.selected else None


@dataclass(frozen=True)
class MemberEnrollSubmission:
    # Each user_<pk> field's cleaned value, in the form's field order.
    choices: dict[int, str]
    guests: int | None
    # The full page's "include" boxes, not the fragment's explicit actions.
    desired: bool


class SkipReason(StrEnum):
    NO_ENROLLMENT_TO_CANCEL = auto()
    SESSION_HOST = auto()
    NOT_AVAILABLE = auto()
    TIME_CONFLICT = auto()
    MANAGES_OWN = auto()


@dataclass(frozen=True)
class SkippedPerson:
    name: str
    reason: SkipReason


@dataclass
class MemberEnrollOutcome:
    enrolled: list[str] = field(default_factory=list)
    waitlisted: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    skipped: list[SkippedPerson] = field(default_factory=list)
    # Final +N guest headcount after this submit; None when untouched.
    guest_total: int | None = None


@dataclass(frozen=True)
class AllowanceRefusal:
    user_id: int
    name: str
    used: int
    allowed: int
    available: int


class MemberEnrollErrorCode(StrEnum):
    SESSION_NOT_FOUND = auto()
    # Unscheduled, and the viewer holds nothing on it to manage.
    NO_ENROLLMENT_CONFIG = auto()
    BANNED = auto()
    INVALID_PARTY = auto()
    # A submit that takes a seat while no window can seat the session.
    NO_ELIGIBLE_WINDOW = auto()


class MemberEnrollError(Exception):
    def __init__(self, code: MemberEnrollErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


class SeatsShortError(Exception):
    def __init__(self, *, requested: int, available: int, blame_guests: bool) -> None:
        super().__init__(requested, available)
        self.requested = requested
        self.available = available
        self.blame_guests = blame_guests


class AllowanceSpentError(Exception):
    """The passes ran out between the form's check and the seat locks."""

    def __init__(self, refusal: AllowanceRefusal) -> None:
        super().__init__(refusal.user_id)
        self.refusal = refusal


class NothingToChangeError(Exception):
    def __init__(self, *, quiet: bool) -> None:
        super().__init__()
        # The submit stated who should be in and nobody moved: "no changes",
        # rather than a nudge to select someone.
        self.quiet = quiet


@dataclass(frozen=True)
class EnrollFooterDTO:
    seats: SessionCardStatsDTO
    viewer_status: str | None


class MemberEnrollmentRepositoryProtocol(SeatRepositoryProtocol, Protocol):
    # Raises NotFoundError when no such session is in the sphere's event.
    def read_session(
        self, *, session_id: int, event_slug: str, sphere_id: int
    ) -> EnrollSessionDTO: ...

    def read_seats(self, session_id: int) -> SessionCardStatsDTO: ...

    # Who holds any row in a session whose slot overlaps this one's.
    def overlapping_user_ids(
        self, *, session_id: int, user_ids: list[int]
    ) -> set[int]: ...

    # Scheduled sessions of the event each person waits for.
    def waitlist_counts(
        self, *, event_id: int, user_ids: list[int]
    ) -> dict[int, int]: ...

    def guest_count(self, *, session_id: int, host_id: int) -> int: ...

    # Deletes the host's `count` most recent guests, throwaway users and all.
    def release_guests(self, *, session_id: int, host_id: int, count: int) -> None: ...


class MemberEnrollmentServiceProtocol(Protocol):
    def read_page(self, query: MemberEnrollQuery) -> MemberEnrollPageDTO: ...

    def allowance_refusal(
        self, *, page: MemberEnrollPageDTO, choices: dict[int, str]
    ) -> AllowanceRefusal | None: ...

    def submit(
        self, *, page: MemberEnrollPageDTO, submission: MemberEnrollSubmission
    ) -> MemberEnrollOutcome: ...

    def read_footer(self, *, session_id: int, viewer_id: int) -> EnrollFooterDTO: ...
