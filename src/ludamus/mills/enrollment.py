"""Waiting-list promotion service.

Owns the promotion / offer-lifecycle decisions and the transactional boundary,
delegating IO to injected ports (repository, notifier, scheduler). Pure
selection lives in `specs.enrollment`; everything here is orchestration so the
logic stays unit-testable with fakes.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ludamus.pacts.enrollment import (
    ClaimResult,
    NavbarNotificationsDTO,
    OfferNotification,
    PromotionNotification,
    PromotionResult,
)
from ludamus.pacts.legacy import PromotionMode
from ludamus.specs.enrollment import select_promotable_parties

if TYPE_CHECKING:
    from ludamus.pacts.enrollment import (
        NotificationReadRepositoryProtocol,
        OfferDTO,
        OfferExpirySchedulerProtocol,
        ParticipationPromotionRepositoryProtocol,
        PromotionStateDTO,
        UserNotifierProtocol,
        WaitingParticipantDTO,
    )
    from ludamus.pacts.services import TransactionProtocol

_NAVBAR_NOTIFICATION_LIMIT = 10


def _now() -> datetime:
    return datetime.now(UTC)


def _token() -> str:
    return secrets.token_urlsafe(48)


class WaitlistPromotionService:
    def __init__(
        self,
        transaction: TransactionProtocol,
        participations: ParticipationPromotionRepositoryProtocol,
        notifier: UserNotifierProtocol,
        scheduler: OfferExpirySchedulerProtocol,
    ) -> None:
        self._transaction = transaction
        self._participations = participations
        self._notifier = notifier
        self._scheduler = scheduler

    def fill_freed_seats(self, *, session_id: int) -> PromotionResult:
        # Idempotent / re-entrant: lock the session, pick the next eligible
        # parties (FIFO, whole-party) and either confirm them (AUTO) or hold and
        # offer them (OFFER_CLAIM). Notifications and expiry timers fire only
        # after the mutation commits.
        promotions: list[PromotionNotification] = []
        offers: list[OfferNotification] = []
        expiries: list[tuple[int, datetime]] = []
        result = PromotionResult()

        with self._transaction.atomic():
            if (state := self._participations.lock_and_read_state(session_id)) is None:
                return result
            if not (parties := select_promotable_parties(state)):
                return result
            if state.promotion_mode == PromotionMode.AUTO:
                self._confirm(parties, state, result, promotions)
            else:
                self._offer(parties, state, result, offers, expiries)

        for promotion in promotions:
            self._notifier.notify_promoted(promotion)
        for offer in offers:
            self._notifier.notify_offered(offer)
        for participation_id, run_at in expiries:
            self._scheduler.schedule_expiry(
                participation_id=participation_id, run_at=run_at
            )

        return result

    def _confirm(
        self,
        parties: list[list[WaitingParticipantDTO]],
        state: PromotionStateDTO,
        result: PromotionResult,
        promotions: list[PromotionNotification],
    ) -> None:
        for party in parties:
            ids = [p.participation_id for p in party]
            self._participations.confirm(ids)
            result.promoted.extend(ids)
            lead = party[0]
            promotions.append(
                PromotionNotification(
                    recipient_user_id=lead.recipient_user_id,
                    recipient_email=lead.recipient_email,
                    session_id=state.session_id,
                    session_title=state.session_title,
                    event_slug=state.event_slug,
                )
            )

    def _offer(
        self,
        parties: list[list[WaitingParticipantDTO]],
        state: PromotionStateDTO,
        result: PromotionResult,
        offers: list[OfferNotification],
        expiries: list[tuple[int, datetime]],
    ) -> None:
        now = _now()
        expires_at = now + state.offer_claim_window
        for party in parties:
            ids = [p.participation_id for p in party]
            token = _token()
            self._participations.offer(
                ids, offered_at=now, offer_expires_at=expires_at, claim_token=token
            )
            result.offered.extend(ids)
            lead = party[0]
            offers.append(
                OfferNotification(
                    recipient_user_id=lead.recipient_user_id,
                    recipient_email=lead.recipient_email,
                    session_id=state.session_id,
                    session_title=state.session_title,
                    event_slug=state.event_slug,
                    claim_token=token,
                    offer_expires_at=expires_at,
                )
            )
            expiries.append((ids[0], expires_at))

    def peek_offer(self, *, token: str) -> OfferDTO | None:
        return self._participations.read_offer_by_token(token)

    def claim_offer(self, *, token: str) -> ClaimResult:
        # Confirm a whole offered party from its single-use claim token. The
        # status + token guard makes claim and expiry race-safe: whichever runs
        # first flips the party out of OFFERED and the other becomes a no-op.
        with self._transaction.atomic():
            if (offer := self._participations.read_offer_by_token(token)) is None:
                return ClaimResult(success=False, reason="not_found")
            if _now() > offer.offer_expires_at:
                return ClaimResult(
                    success=False,
                    reason="expired",
                    session_id=offer.session_id,
                    event_slug=offer.event_slug,
                )
            self._participations.mark_claimed(offer.participant_ids, claimed_at=_now())
            return ClaimResult(
                success=True, session_id=offer.session_id, event_slug=offer.event_slug
            )

    def expire_offer(self, *, participation_id: int) -> PromotionResult:
        # Drop a lapsed offered party (terminal), notify them, then re-enter
        # fill_freed_seats so the released seats roll on to the next party.
        with self._transaction.atomic():
            offer = self._participations.read_offer_by_participation(participation_id)
            if offer is None:
                return PromotionResult()
            if _now() <= offer.offer_expires_at:
                return PromotionResult()
            self._participations.drop(offer.participant_ids)
            notification = PromotionNotification(
                recipient_user_id=offer.recipient_user_id,
                recipient_email=offer.recipient_email,
                session_id=offer.session_id,
                session_title=offer.session_title,
                event_slug=offer.event_slug,
            )
            session_id = offer.session_id

        self._notifier.notify_offer_expired(notification)
        return self.fill_freed_seats(session_id=session_id)


class NotificationsService:
    """Read path for the navbar notifications dropdown + mark-as-read."""

    def __init__(
        self,
        transaction: TransactionProtocol,
        notifications: NotificationReadRepositoryProtocol,
    ) -> None:
        self._transaction = transaction
        self._notifications = notifications

    def get_navbar(self, user_id: int) -> NavbarNotificationsDTO:
        return NavbarNotificationsDTO(
            unread_count=self._notifications.unread_count(user_id),
            items=self._notifications.list_recent(user_id, _NAVBAR_NOTIFICATION_LIMIT),
        )

    def mark_all_read(self, user_id: int) -> None:
        with self._transaction.atomic():
            self._notifications.mark_all_read(user_id)
