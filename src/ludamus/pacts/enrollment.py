"""Protocols and DTOs for waiting-list promotion (offer-and-claim).

Bottom-layer contracts consumed by the `WaitlistPromotionService` mill. The
service depends on these ports (repository, notifier, scheduler) so the
promotion / offer-lifecycle decisions stay unit-testable with fakes.
"""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.legacy import PromotionMode, SessionParticipationStatus

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ludamus.pacts.crowd import UserDTO
    from ludamus.pacts.party import HeldSeatNotification

# Sentinel for "no membership limit" so the whole-party fit check is a plain
# integer comparison in the pure selection invariant.
UNLIMITED_SLOTS = 1_000_000_000


class WaitingParticipantDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    participation_id: int
    user_id: int
    # Party this seat was enrolled through; None for solo/legacy rows.
    party_id: int | None = None
    # Party leader sponsoring a login-less companion; None for a self-owned
    # account (a real user always spends their own allowance).
    sponsor_id: int | None
    full_name: str
    email: str
    creation_time: datetime
    # Re-validated against the session's current placement by the repo.
    has_conflict: bool
    # Remaining distinct-user membership slots for this participant's slot
    # owner in the event; UNLIMITED_SLOTS when no limit applies.
    owner_slots_remaining: int
    # Who is told about the seat — the sponsoring leader for a login-less
    # companion, otherwise the participant themselves. Shared across a party.
    recipient_user_id: int
    recipient_email: str

    @property
    def effective_slot_owner(self) -> int:
        return self.sponsor_id if self.sponsor_id is not None else self.user_id

    @property
    def promotion_group_key(self) -> tuple[str, int]:
        # Seats enrolled through a party promote as that party; everything else
        # falls back to grouping by slot owner (a leader plus the companions
        # they enrolled without choosing a party still move together).
        if self.party_id is not None:
            return ("party", self.party_id)
        return ("owner", self.effective_slot_owner)


class PromotionStateDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: int
    session_title: str
    event_slug: str
    promotion_mode: PromotionMode
    offer_claim_window: timedelta
    presenter_id: int | None
    available_seats: int
    # WAITING participations, ordered FIFO by creation_time.
    waiting: list[WaitingParticipantDTO]


class OfferRecipientDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    email: str


def distinct_recipients(
    candidates: Iterable[tuple[int, str]],
) -> list[OfferRecipientDTO]:
    # One message per person, first mention wins: a party of real co-members
    # hears about its seats individually, while a leader sponsoring several
    # login-less companions still gets a single message.
    recipients: list[OfferRecipientDTO] = []
    seen: set[int] = set()
    for user_id, email in candidates:
        if user_id not in seen:
            seen.add(user_id)
            recipients.append(OfferRecipientDTO(user_id=user_id, email=email))
    return recipients


class OfferDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: int
    session_title: str
    event_slug: str
    # All participations sharing this offer (whole party).
    participant_ids: list[int]
    # Everyone who should hear about this offer: each real member for
    # themselves, the sponsoring leader for login-less companions. Distinct.
    recipients: list[OfferRecipientDTO]
    offer_expires_at: datetime


class PromotionResult(BaseModel):
    # participation ids moved straight to CONFIRMED (AUTO mode)
    promoted: list[int] = []
    # participation ids put on hold as OFFERED (OFFER_CLAIM mode)
    offered: list[int] = []


class ClaimResult(BaseModel):
    success: bool
    session_id: int | None = None
    event_slug: str | None = None
    reason: str | None = None


class SeatHoldRequest(BaseModel):
    # A leader holding a seat for an ACCEPT_INVITES party member (RFC 0001
    # O-9): the member confirms via the claim link before the seat is theirs.
    session_id: int
    session_title: str
    user_id: int
    user_email: str
    party_id: int | None
    actor_name: str


class HeldSeatData(BaseModel):
    # The OFFERED row a held seat materialises as.
    session_id: int
    user_id: int
    party_id: int | None
    offered_at: datetime
    offer_expires_at: datetime
    claim_token: str


class PromotionNotification(BaseModel):
    recipient_user_id: int
    recipient_email: str
    session_id: int
    session_title: str
    event_slug: str


class OfferNotification(BaseModel):
    recipient_user_id: int
    recipient_email: str
    session_id: int
    session_title: str
    event_slug: str
    claim_token: str
    offer_expires_at: datetime


class NotificationDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pk: int
    kind: str
    title: str
    body: str
    url: str
    creation_time: datetime
    is_read: bool


class NavbarNotificationsDTO(BaseModel):
    unread_count: int
    items: list[NotificationDTO]


class NotificationReadRepositoryProtocol(Protocol):
    def unread_count(self, user_id: int) -> int: ...
    def list_recent(self, user_id: int, limit: int) -> list[NotificationDTO]: ...
    def mark_all_read(self, user_id: int) -> None: ...


class NotificationsServiceProtocol(Protocol):
    def get_navbar(self, user_id: int) -> NavbarNotificationsDTO: ...
    def mark_all_read(self, user_id: int) -> None: ...


class ParticipationPromotionRepositoryProtocol(Protocol):
    def lock_and_read_state(self, session_id: int) -> PromotionStateDTO | None:
        """Lock the session row and read everything needed to promote.

        Returns None when the session cannot accept promotions (no agenda item
        / no enrollment config). Counts CONFIRMED + OFFERED as occupying seats.
        """

    def confirm(self, participation_ids: list[int]) -> None: ...

    def offer(
        self,
        participation_ids: list[int],
        *,
        offered_at: datetime,
        offer_expires_at: datetime,
        claim_token: str,
    ) -> None: ...

    def create_offered(self, seat: HeldSeatData) -> int: ...

    def read_offer_claim_window(self, session_id: int) -> timedelta: ...

    def read_offer_by_token(self, token: str) -> OfferDTO | None: ...

    def read_offer_by_participation(self, participation_id: int) -> OfferDTO | None: ...

    def mark_claimed(
        self, participation_ids: list[int], *, claimed_at: datetime
    ) -> None: ...

    def drop(self, participation_ids: list[int]) -> None: ...


class UserNotifierProtocol(Protocol):
    def notify_promoted(self, notification: PromotionNotification) -> None: ...
    def notify_offered(self, notification: OfferNotification) -> None: ...
    def notify_offer_expired(self, notification: PromotionNotification) -> None: ...
    def notify_seat_held(self, notification: HeldSeatNotification) -> None: ...


class OfferExpirySchedulerProtocol(Protocol):
    def schedule_expiry(self, *, participation_id: int, run_at: datetime) -> None: ...


class WaitlistPromotionServiceProtocol(Protocol):
    def fill_freed_seats(self, *, session_id: int) -> PromotionResult: ...
    def hold_seat(self, *, hold: SeatHoldRequest) -> None: ...
    def peek_offer(self, *, token: str) -> OfferDTO | None: ...
    def claim_offer(self, *, token: str) -> ClaimResult: ...
    def decline_offer(self, *, token: str) -> ClaimResult: ...
    def expire_offer(self, *, participation_id: int) -> PromotionResult: ...


class AnonymousEnrollmentErrorCode(StrEnum):
    EVENT_NOT_FOUND = "event_not_found"
    NOT_AVAILABLE_FOR_EVENT = "not_available_for_event"
    SESSION_NOT_FOUND = "session_not_found"
    # The session belongs to a different event than the visitor's anonymous
    # session was activated for.
    NOT_FOR_THIS_SESSION = "not_for_this_session"
    # The session has no agenda item, so there is nothing to enroll into.
    NO_ENROLLMENT_CONFIG = "no_enrollment_config"
    # Anonymous enrollment for this session is no longer (or not yet) open.
    ENROLLMENT_CLOSED = "enrollment_closed"
    # No code in the visitor's anonymous session state.
    SESSION_EXPIRED = "session_expired"
    USER_NOT_FOUND = "user_not_found"
    NAME_REQUIRED = "name_required"
    NO_ENROLLMENTS = "no_enrollments"


class AnonymousEnrollmentError(Exception):
    def __init__(
        self, code: AnonymousEnrollmentErrorCode, *, event_slug: str | None = None
    ) -> None:
        super().__init__(code.value)
        self.code = code
        # Where the visitor should be sent back to, when an event page is a
        # better landing spot than the index.
        self.event_slug = event_slug


class AnonymousEventDTO(BaseModel):
    event_id: int
    slug: str
    allows_anonymous_enrollment: bool


class AnonymousSessionContextDTO(BaseModel):
    session_id: int
    event_id: int
    event_slug: str
    has_agenda_item: bool
    # An active enrollment config allows anonymous enrollment and covers this
    # session right now.
    allows_anonymous_enrollment: bool
    title: str
    display_name: str
    description: str
    min_age: int
    enrolled_count: int
    waiting_count: int
    effective_participants_limit: int
    # None when the session has no agenda item (nowhere assigned yet).
    space_name: str | None
    start_time: datetime | None
    end_time: datetime | None


class AnonymousSeatingDTO(BaseModel):
    is_full: bool
    title: str


class AnonymousActivationDTO(BaseModel):
    code: str
    event_id: int
    event_slug: str


class AnonymousEnrollPageDTO(BaseModel):
    session: AnonymousSessionContextDTO
    user_name: str
    anonymous_code: str
    needs_user_data: bool
    enrollment_status: SessionParticipationStatus | None

    @property
    def is_enrolled(self) -> bool:
        return self.enrollment_status is not None


class AnonymousEnrollOutcome(StrEnum):
    ENROLLED = "enrolled"
    WAITLISTED = "waitlisted"
    CONFLICT = "conflict"


class AnonymousEnrollResultDTO(BaseModel):
    outcome: AnonymousEnrollOutcome
    session_title: str
    event_slug: str


class AnonymousCancelResultDTO(BaseModel):
    cancelled: bool
    session_title: str
    event_slug: str


class AnonymousLoadDTO(BaseModel):
    event_id: int
    event_slug: str
    site_id: int


class AnonymousEnrollmentRequestDTO(BaseModel):
    # Everything identifying "this visitor acting on this session": URL parts
    # plus the anonymous state the view read from the Django session.
    event_slug: str
    session_id: int
    site_id: int
    anonymous_event_id: int | None
    code: str | None


class AnonymousEnrollmentRepositoryProtocol(Protocol):
    # Raises NotFoundError when no event matches the slug.
    @staticmethod
    def read_event(event_slug: str) -> AnonymousEventDTO: ...

    @staticmethod
    def event_slug_by_id(event_id: int) -> str | None: ...

    # Raises NotFoundError when no session matches within the site.
    @staticmethod
    def read_session(
        *, session_id: int, event_slug: str, site_id: int
    ) -> AnonymousSessionContextDTO: ...

    @staticmethod
    def read_participation_status(
        *, session_id: int, user_id: int
    ) -> SessionParticipationStatus | None: ...

    @staticmethod
    def has_conflicts(*, session_id: int, user: UserDTO) -> bool: ...

    # Locks the session row for the enrollment mutation that follows.
    @staticmethod
    def lock_seating(session_id: int) -> AnonymousSeatingDTO: ...

    @staticmethod
    def create_or_confirm(*, session_id: int, user_id: int) -> None: ...

    @staticmethod
    def create_waiting(*, session_id: int, user_id: int) -> None: ...

    # Deletes the user's participation, returning its status (None if absent).
    @staticmethod
    def delete_participation(
        *, session_id: int, user_id: int
    ) -> SessionParticipationStatus | None: ...

    @staticmethod
    def first_enrollment_event(user_id: int) -> AnonymousLoadDTO | None: ...


class AnonymousEnrollmentServiceProtocol(Protocol):
    def get_user_by_code(self, code: str) -> UserDTO: ...

    def activate(self, *, event_slug: str) -> AnonymousActivationDTO: ...

    def get_enroll_page(
        self, enrollment_request: AnonymousEnrollmentRequestDTO
    ) -> AnonymousEnrollPageDTO: ...

    def enroll(
        self, enrollment_request: AnonymousEnrollmentRequestDTO, name: str
    ) -> AnonymousEnrollResultDTO: ...

    def cancel(
        self, enrollment_request: AnonymousEnrollmentRequestDTO, name: str
    ) -> AnonymousCancelResultDTO: ...

    def load_by_code(self, *, code: str) -> AnonymousLoadDTO: ...

    def event_slug_by_id(self, event_id: int) -> str | None: ...
