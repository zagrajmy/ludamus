"""Protocols and DTOs for waiting-list promotion (offer-and-claim).

Bottom-layer contracts consumed by the `WaitlistPromotionService` mill. The
service depends on these ports (repository, notifier, scheduler) so the
promotion / offer-lifecycle decisions stay unit-testable with fakes.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.legacy import PromotionMode

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ludamus.pacts.crowd import UserDTO, UserRepositoryProtocol
    from ludamus.pacts.legacy import (
        EnrollmentConfigRepositoryProtocol,
        EventDTO,
        TicketAPIProtocol,
        VirtualEnrollmentConfig,
    )
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

    # One representative participation id per lapsed offered party (the caller
    # expands to the whole party from the shared claim token).
    def list_lapsed_offers(self, now: datetime) -> list[int]: ...

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


class GuestSeatData(BaseModel):
    # The CONFIRMED row a +N headcount guest materialises as.
    session_id: int
    user_id: int
    party_id: int | None
    enrolled_by_id: int


class EnrollmentParticipationRepositoryProtocol(Protocol):
    @staticmethod
    def occupying_user_ids(*, user_ids: list[int], event_id: int) -> set[int]: ...

    @staticmethod
    def create_confirmed(seat: GuestSeatData) -> None: ...


@dataclass(frozen=True)
class EnrollmentRepos:
    # The repos the enrollment service reads rosters and writes guest seats
    # through; `ticket_api` rides along because membership lookups always
    # accompany the config reads. Mirrors the `ImportRepos` bundle the
    # submissions services use to keep a many-repo constructor within the
    # argument-count limit.
    users: UserRepositoryProtocol
    anonymous_users: UserRepositoryProtocol
    enrollment_configs: EnrollmentConfigRepositoryProtocol
    participations: EnrollmentParticipationRepositoryProtocol
    ticket_api: TicketAPIProtocol


class EnrollmentServiceProtocol(Protocol):
    def read_viewer(self, slug: str) -> UserDTO: ...

    def read_users(self, pks: list[int]) -> list[UserDTO]: ...

    def virtual_config(
        self, *, event: EventDTO, user_email: str
    ) -> VirtualEnrollmentConfig | None: ...

    def has_slot_access(self, *, event: EventDTO, user_email: str) -> bool: ...

    def can_enroll_users(
        self,
        *,
        users: list[UserDTO],
        event: EventDTO,
        virtual_config: VirtualEnrollmentConfig,
        users_to_enroll: list[UserDTO],
    ) -> bool: ...

    def get_used_slots(self, *, users: list[UserDTO], event: EventDTO) -> int: ...

    def get_vc_available_slots(
        self,
        *,
        users: list[UserDTO],
        event: EventDTO,
        virtual_config: VirtualEnrollmentConfig,
    ) -> int: ...

    def create_guests(
        self,
        *,
        session_id: int,
        count: int,
        party_id: int | None,
        enrolled_by_id: int,
        viewer_name: str,
    ) -> None: ...


class WaitlistPromotionServiceProtocol(Protocol):
    def fill_freed_seats(self, *, session_id: int) -> PromotionResult: ...
    def hold_seat(self, *, hold: SeatHoldRequest) -> None: ...
    def peek_offer(self, *, token: str) -> OfferDTO | None: ...
    def claim_offer(self, *, token: str) -> ClaimResult: ...
    def decline_offer(self, *, token: str) -> ClaimResult: ...
    def expire_offer(self, *, participation_id: int) -> PromotionResult: ...
