"""Protocols and DTOs for waiting-list promotion (offer-and-claim).

Bottom-layer contracts consumed by the `WaitlistPromotionService` mill. The
service depends on these ports (repository, notifier, scheduler) so the
promotion / offer-lifecycle decisions stay unit-testable with fakes.
"""

from datetime import datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ludamus.pacts.legacy import PromotionMode

# Sentinel for "no membership limit" so the whole-party fit check is a plain
# integer comparison in the pure selection invariant.
UNLIMITED_SLOTS = 1_000_000_000


class WaitingParticipantDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    participation_id: int
    user_id: int
    # Effective manager for guardian-managed minors; None for a lone adult.
    manager_id: int | None
    full_name: str
    email: str
    is_active: bool
    creation_time: datetime
    # Re-validated against the session's current placement by the repo.
    has_conflict: bool
    # Remaining distinct-user membership slots for this participant's manager
    # (or self) in the event; UNLIMITED_SLOTS when no limit applies.
    manager_slots_remaining: int
    # Who is told about the seat — the managing guardian for a minor, otherwise
    # the participant themselves. Shared across a party.
    recipient_user_id: int
    recipient_email: str

    @property
    def effective_manager_id(self) -> int:
        return self.manager_id if self.manager_id is not None else self.user_id


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


class OfferDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: int
    session_title: str
    event_slug: str
    # All participations sharing this offer (whole party).
    participant_ids: list[int]
    recipient_user_id: int
    recipient_email: str
    offer_expires_at: datetime
    is_claimable: bool


class PromotionResult(BaseModel):
    # participation ids moved straight to CONFIRMED (AUTO mode)
    promoted: list[int] = []
    # participation ids put on hold as OFFERED (OFFER_CLAIM mode)
    offered: list[int] = []
    # human-readable skip reasons, for observability
    skipped: list[str] = []


class ClaimResult(BaseModel):
    success: bool
    session_id: int | None = None
    event_slug: str | None = None
    reason: str | None = None


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


class OfferExpirySchedulerProtocol(Protocol):
    def schedule_expiry(self, *, participation_id: int, run_at: datetime) -> None: ...


class WaitlistPromotionServiceProtocol(Protocol):
    def fill_freed_seats(self, *, session_id: int) -> PromotionResult: ...
    def peek_offer(self, *, token: str) -> OfferDTO | None: ...
    def claim_offer(self, *, token: str) -> ClaimResult: ...
    def expire_offer(self, *, participation_id: int) -> PromotionResult: ...
