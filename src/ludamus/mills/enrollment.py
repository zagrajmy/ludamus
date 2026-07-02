"""Waiting-list promotion service.

Owns the promotion / offer-lifecycle decisions and the transactional boundary,
delegating IO to injected ports (repository, notifier, scheduler). Pure
selection lives in `specs.enrollment`; everything here is orchestration so the
logic stays unit-testable with fakes.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import TYPE_CHECKING

from ludamus.pacts import (
    MembershipAPIError,
    UserEnrollmentConfigData,
    VirtualEnrollmentConfig,
)
from ludamus.pacts.crowd import UserData, UserDTO, UserType
from ludamus.pacts.enrollment import (
    ClaimResult,
    HeldSeatData,
    NavbarNotificationsDTO,
    OfferNotification,
    PromotionNotification,
    PromotionResult,
    distinct_recipients,
)
from ludamus.pacts.legacy import PromotionMode
from ludamus.pacts.party import HeldSeatNotification
from ludamus.specs.enrollment import select_promotable_parties

if TYPE_CHECKING:
    from ludamus.pacts import (
        EnrollmentConfigDTO,
        EnrollmentConfigRepositoryProtocol,
        EventDTO,
        TicketAPIProtocol,
        UserEnrollmentConfigDTO,
    )
    from ludamus.pacts.crowd import UserRepositoryProtocol
    from ludamus.pacts.enrollment import (
        NotificationReadRepositoryProtocol,
        OfferDTO,
        OfferExpirySchedulerProtocol,
        OfferRecipientDTO,
        ParticipationPromotionRepositoryProtocol,
        PromotionStateDTO,
        SeatHoldRequest,
        UserNotifierProtocol,
        WaitingParticipantDTO,
    )
    from ludamus.pacts.services import TransactionProtocol

_NAVBAR_NOTIFICATION_LIMIT = 10


def _now() -> datetime:
    return datetime.now(UTC)


def _token() -> str:
    return secrets.token_urlsafe(48)


def _party_recipients(party: list[WaitingParticipantDTO]) -> list[OfferRecipientDTO]:
    return distinct_recipients((p.recipient_user_id, p.recipient_email) for p in party)


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
            promotions.extend(
                PromotionNotification(
                    recipient_user_id=recipient.user_id,
                    recipient_email=recipient.email,
                    session_id=state.session_id,
                    session_title=state.session_title,
                    event_slug=state.event_slug,
                )
                for recipient in _party_recipients(party)
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
            offers.extend(
                OfferNotification(
                    recipient_user_id=recipient.user_id,
                    recipient_email=recipient.email,
                    session_id=state.session_id,
                    session_title=state.session_title,
                    event_slug=state.event_slug,
                    claim_token=token,
                    offer_expires_at=expires_at,
                )
                for recipient in _party_recipients(party)
            )
            expiries.append((ids[0], expires_at))

    def hold_seat(self, *, hold: SeatHoldRequest) -> None:
        # A held seat is an OFFERED row with a personal claim token — the same
        # shape a waitlist offer uses — so claiming, declining, and expiry all
        # ride the existing offer machinery and release only this seat. The
        # notification is written with the row (it must roll back together);
        # the expiry timer is armed after, like fill_freed_seats does.
        now = _now()
        with self._transaction.atomic():
            expires_at = now + self._participations.read_offer_claim_window(
                hold.session_id
            )
            token = _token()
            participation_id = self._participations.create_offered(
                HeldSeatData(
                    session_id=hold.session_id,
                    user_id=hold.user_id,
                    party_id=hold.party_id,
                    offered_at=now,
                    offer_expires_at=expires_at,
                    claim_token=token,
                )
            )
            self._notifier.notify_seat_held(
                HeldSeatNotification(
                    recipient_user_id=hold.user_id,
                    recipient_email=hold.user_email,
                    actor_name=hold.actor_name,
                    session_id=hold.session_id,
                    session_title=hold.session_title,
                    claim_token=token,
                    offer_expires_at=expires_at,
                )
            )
        self._scheduler.schedule_expiry(
            participation_id=participation_id, run_at=expires_at
        )

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

    def decline_offer(self, *, token: str) -> ClaimResult:
        # Token-authorised way out: a member turning down a held seat or a
        # waiter passing on an offer. Drops the whole offered party (the offer
        # is party-wide, like claiming) and rolls the freed seats on. The
        # status guard in drop() makes a racing claim/expiry a no-op here.
        with self._transaction.atomic():
            if (offer := self._participations.read_offer_by_token(token)) is None:
                return ClaimResult(success=False, reason="not_found")
            self._participations.drop(offer.participant_ids)
            session_id = offer.session_id
            event_slug = offer.event_slug

        self.fill_freed_seats(session_id=session_id)
        return ClaimResult(success=True, session_id=session_id, event_slug=event_slug)

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
            notifications = [
                PromotionNotification(
                    recipient_user_id=recipient.user_id,
                    recipient_email=recipient.email,
                    session_id=offer.session_id,
                    session_title=offer.session_title,
                    event_slug=offer.event_slug,
                )
                for recipient in offer.recipients
            ]
            session_id = offer.session_id

        for notification in notifications:
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


class AnonymousEnrollmentService:
    SLUG_TEMPLATE = "code_{code}"

    def __init__(self, user_repository: UserRepositoryProtocol) -> None:
        self._user_repository = user_repository

    def get_user_by_code(self, code: str) -> UserDTO:
        slug = self.SLUG_TEMPLATE.format(code=code)
        user = self._user_repository.read(slug)
        return UserDTO.model_validate(user)

    def build_user(self, code: str) -> UserData:
        return UserData(
            username=f"anon_{token_urlsafe(8).lower()}",
            slug=self.SLUG_TEMPLATE.format(code=code),
            user_type=UserType.ANONYMOUS,
            is_active=False,
        )


def _refresh_user_config_from_api(
    *,
    user_config: UserEnrollmentConfigDTO,
    ticket_api: TicketAPIProtocol,
    enrollment_config_repo: EnrollmentConfigRepositoryProtocol,
) -> UserEnrollmentConfigDTO | None:
    try:
        membership_count = ticket_api.fetch_membership_count(user_config.user_email)
    except MembershipAPIError:
        return user_config

    current_time = datetime.now(tz=UTC)

    if membership_count == 0:
        user_config.allowed_slots = 0
        user_config.last_check = current_time
        enrollment_config_repo.update_user_config(user_config)
        return None

    user_config.allowed_slots = membership_count
    user_config.last_check = current_time
    enrollment_config_repo.update_user_config(user_config)
    return user_config


def _create_user_config_from_api(
    *,
    enrollment_config: EnrollmentConfigDTO,
    user_email: str,
    ticket_api: TicketAPIProtocol,
    enrollment_config_repo: EnrollmentConfigRepositoryProtocol,
) -> UserEnrollmentConfigDTO | None:

    try:
        membership_count = ticket_api.fetch_membership_count(user_email)
    except MembershipAPIError:
        return None

    current_time = datetime.now(tz=UTC)
    return enrollment_config_repo.create_user_config(
        UserEnrollmentConfigData(
            enrollment_config_id=enrollment_config.pk,
            user_email=user_email,
            allowed_slots=membership_count,
            fetched_from_api=True,
            last_check=current_time,
        )
    )


def get_or_create_user_enrollment_config(  # noqa: PLR0913
    *,
    enrollment_config: EnrollmentConfigDTO,
    user_email: str,
    ticket_api: TicketAPIProtocol,
    check_interval_minutes: int,
    existing_user_config: UserEnrollmentConfigDTO | None,
    enrollment_config_repo: EnrollmentConfigRepositoryProtocol,
) -> UserEnrollmentConfigDTO | None:
    if existing_user_config:
        if existing_user_config.allowed_slots > 0:
            return existing_user_config

        time_threshold = datetime.now(tz=UTC) - timedelta(
            minutes=check_interval_minutes
        )

        if (
            not existing_user_config.last_check
            or existing_user_config.last_check < time_threshold
        ):
            return _refresh_user_config_from_api(
                user_config=existing_user_config,
                ticket_api=ticket_api,
                enrollment_config_repo=enrollment_config_repo,
            )

        return None

    return _create_user_config_from_api(
        enrollment_config=enrollment_config,
        user_email=user_email,
        ticket_api=ticket_api,
        enrollment_config_repo=enrollment_config_repo,
    )


def get_user_enrollment_config(
    *,
    event: EventDTO,
    user_email: str,
    enrollment_config_repo: EnrollmentConfigRepositoryProtocol,
    ticket_api: TicketAPIProtocol,
    check_interval_minutes: int,
) -> VirtualEnrollmentConfig | None:
    virtual_config = VirtualEnrollmentConfig()

    now = datetime.now(tz=UTC)
    for config in enrollment_config_repo.read_list(
        event.pk, max_start_time=now, min_end_time=now
    ):
        existing_user_config = enrollment_config_repo.read_user_config(
            config, user_email
        )
        if api_user_config := get_or_create_user_enrollment_config(
            enrollment_config=config,
            user_email=user_email,
            ticket_api=ticket_api,
            check_interval_minutes=check_interval_minutes,
            existing_user_config=existing_user_config,
            enrollment_config_repo=enrollment_config_repo,
        ):
            virtual_config.allowed_slots += api_user_config.allowed_slots
            virtual_config.has_user_config = True
        elif existing_user_config:
            virtual_config.allowed_slots += existing_user_config.allowed_slots
            virtual_config.has_user_config = True

        email_domain = (
            user_email.split("@")[1] if (user_email and "@" in user_email) else ""
        )
        if email_domain and (
            domain_config := enrollment_config_repo.read_domain_config(
                config, email_domain
            )
        ):
            virtual_config.allowed_slots += domain_config.allowed_slots_per_user
            virtual_config.has_domain_config = True

    return (
        virtual_config
        if (virtual_config.has_user_config or virtual_config.has_domain_config)
        else None
    )
