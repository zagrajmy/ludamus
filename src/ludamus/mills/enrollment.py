"""Enrollment services: waitlist promotion, anonymous enrollment, notifications.

Each service owns its decisions and transactional boundary, delegating IO to
injected ports (repositories, notifier, scheduler) so the logic stays
unit-testable with fakes. Pure promotion selection lives in
`specs.enrollment`. Also holds the user-enrollment-config helpers backed by
the ticket API.
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
    AnonymousActivationDTO,
    AnonymousCancelResultDTO,
    AnonymousEnrollmentError,
    AnonymousEnrollmentErrorCode,
    AnonymousEnrollmentServiceProtocol,
    AnonymousEnrollOutcome,
    AnonymousEnrollPageDTO,
    AnonymousEnrollResultDTO,
    AnonymousLoadDTO,
    ClaimResult,
    EnrollmentServiceProtocol,
    GuestSeatData,
    HeldSeatData,
    NavbarNotificationsDTO,
    OfferNotification,
    PromotionNotification,
    PromotionResult,
    distinct_recipients,
)
from ludamus.pacts.legacy import (
    OCCUPYING_PARTICIPATION_STATUSES,
    NotFoundError,
    PromotionMode,
)
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
        AnonymousEnrollmentRepositoryProtocol,
        AnonymousEnrollmentRequestDTO,
        AnonymousSessionContextDTO,
        EnrollmentParticipationRepositoryProtocol,
        EnrollmentRepos,
        NotificationReadRepositoryProtocol,
        OfferDTO,
        OfferExpirySchedulerProtocol,
        OfferRecipientDTO,
        ParticipationPromotionRepositoryProtocol,
        PromotionStateDTO,
        SeatHoldRequest,
        UserNotifierProtocol,
        WaitingParticipantDTO,
        WaitlistPromotionServiceProtocol,
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


def build_anonymous_user(slug: str, name: str = "") -> UserData:
    # The single recipe for throwaway ANONYMOUS accounts (code-based
    # self-enrollment, +N headcount guests); only the slug/name vary.
    return UserData(
        username=f"anon_{token_urlsafe(8).lower()}",
        slug=slug,
        name=name,
        user_type=UserType.ANONYMOUS,
        is_active=False,
    )


class AnonymousEnrollmentService(AnonymousEnrollmentServiceProtocol):
    SLUG_TEMPLATE = "code_{code}"

    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        user_repository: UserRepositoryProtocol,
        enrollment_repository: AnonymousEnrollmentRepositoryProtocol,
        waitlist_promotion: WaitlistPromotionServiceProtocol,
    ) -> None:
        self._transaction = transaction
        self._user_repository = user_repository
        self._enrollment_repository = enrollment_repository
        self._waitlist_promotion = waitlist_promotion

    def get_user_by_code(self, code: str) -> UserDTO:
        slug = self.SLUG_TEMPLATE.format(code=code)
        user = self._user_repository.read(slug)
        return UserDTO.model_validate(user)

    def build_user(self, code: str) -> UserData:
        return build_anonymous_user(self.SLUG_TEMPLATE.format(code=code))

    def activate(self, *, event_slug: str) -> AnonymousActivationDTO:
        try:
            event = self._enrollment_repository.read_event(event_slug)
        except NotFoundError:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.EVENT_NOT_FOUND
            ) from None
        if not event.allows_anonymous_enrollment:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.NOT_AVAILABLE_FOR_EVENT,
                event_slug=event.slug,
            )
        code = token_urlsafe(4).lower()
        self._user_repository.create(self.build_user(code))
        return AnonymousActivationDTO(
            code=code, event_id=event.event_id, event_slug=event.slug
        )

    def get_enroll_page(
        self, enrollment_request: AnonymousEnrollmentRequestDTO
    ) -> AnonymousEnrollPageDTO:
        session, user = self._validate(
            enrollment_request, require_active_enrollment=False
        )
        status = self._enrollment_repository.read_participation_status(
            session_id=session.session_id, user_id=user.pk
        )
        if status is None and not session.allows_anonymous_enrollment:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.ENROLLMENT_CLOSED,
                event_slug=session.event_slug,
            )
        return AnonymousEnrollPageDTO(
            session=session,
            user_name=user.full_name,
            anonymous_code=user.slug.removeprefix("code_"),
            needs_user_data=not user.name,
            enrollment_status=status,
        )

    def enroll(
        self, enrollment_request: AnonymousEnrollmentRequestDTO, name: str
    ) -> AnonymousEnrollResultDTO:
        session, user = self._validate(
            enrollment_request, require_active_enrollment=True
        )
        self._update_name(user, name)
        if self._enrollment_repository.has_conflicts(
            session_id=session.session_id, user=user
        ):
            return AnonymousEnrollResultDTO(
                outcome=AnonymousEnrollOutcome.CONFLICT,
                session_title=session.title,
                event_slug=session.event_slug,
            )
        with self._transaction.atomic():
            seating = self._enrollment_repository.lock_seating(session.session_id)
            if seating.is_full:
                self._enrollment_repository.create_waiting(
                    session_id=session.session_id, user_id=user.pk
                )
                outcome = AnonymousEnrollOutcome.WAITLISTED
            else:
                self._enrollment_repository.create_or_confirm(
                    session_id=session.session_id, user_id=user.pk
                )
                outcome = AnonymousEnrollOutcome.ENROLLED
        return AnonymousEnrollResultDTO(
            outcome=outcome, session_title=seating.title, event_slug=session.event_slug
        )

    def cancel(
        self, enrollment_request: AnonymousEnrollmentRequestDTO, name: str
    ) -> AnonymousCancelResultDTO:
        session, user = self._validate(
            enrollment_request, require_active_enrollment=False
        )
        self._update_name(user, name)
        with self._transaction.atomic():
            seating = self._enrollment_repository.lock_seating(session.session_id)
            status = self._enrollment_repository.delete_participation(
                session_id=session.session_id, user_id=user.pk
            )
        # A freed confirmed (or held offered) seat promotes/offers the next
        # waiter, who is notified by the promotion service after the mutation
        # commits.
        if status in OCCUPYING_PARTICIPATION_STATUSES:
            self._waitlist_promotion.fill_freed_seats(session_id=session.session_id)
        return AnonymousCancelResultDTO(
            cancelled=status is not None,
            session_title=seating.title,
            event_slug=session.event_slug,
        )

    def load_by_code(self, *, code: str) -> AnonymousLoadDTO:
        try:
            user = self.get_user_by_code(code)
        except NotFoundError:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.USER_NOT_FOUND
            ) from None
        load = self._enrollment_repository.first_enrollment_event(user.pk)
        if load is None:
            raise AnonymousEnrollmentError(AnonymousEnrollmentErrorCode.NO_ENROLLMENTS)
        return load

    def event_slug_by_id(self, event_id: int) -> str | None:
        return self._enrollment_repository.event_slug_by_id(event_id)

    def _validate(
        self,
        enrollment_request: AnonymousEnrollmentRequestDTO,
        *,
        require_active_enrollment: bool,
    ) -> tuple[AnonymousSessionContextDTO, UserDTO]:
        request = enrollment_request
        try:
            session = self._enrollment_repository.read_session(
                session_id=request.session_id,
                event_slug=request.event_slug,
                site_id=request.site_id,
            )
        except NotFoundError:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.SESSION_NOT_FOUND
            ) from None
        # Unscheduled sessions (no agenda item) have no enrollment to join.
        if not session.has_agenda_item:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.NO_ENROLLMENT_CONFIG,
                event_slug=self._anonymous_event_slug(request),
            )
        if (
            request.anonymous_event_id is None
            or session.event_id != request.anonymous_event_id
        ):
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.NOT_FOR_THIS_SESSION,
                event_slug=self._anonymous_event_slug(request),
            )
        if require_active_enrollment and not session.allows_anonymous_enrollment:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.ENROLLMENT_CLOSED,
                event_slug=session.event_slug,
            )
        if not request.code:
            raise AnonymousEnrollmentError(AnonymousEnrollmentErrorCode.SESSION_EXPIRED)
        try:
            user = self.get_user_by_code(request.code)
        except NotFoundError:
            raise AnonymousEnrollmentError(
                AnonymousEnrollmentErrorCode.USER_NOT_FOUND
            ) from None
        return session, user

    def _anonymous_event_slug(
        self, enrollment_request: AnonymousEnrollmentRequestDTO
    ) -> str | None:
        if enrollment_request.anonymous_event_id is None:
            return None
        return self._enrollment_repository.event_slug_by_id(
            enrollment_request.anonymous_event_id
        )

    def _update_name(self, user: UserDTO, name: str) -> None:
        if name:
            user.name = name
        if not user.name:
            raise AnonymousEnrollmentError(AnonymousEnrollmentErrorCode.NAME_REQUIRED)
        # Mirrors the legacy view: the raw submitted value is written even
        # when blank, so a cancel posted without a name field clears it.
        self._user_repository.update(user.slug, UserData(name=name))


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


def get_used_slots(
    *,
    users: list[UserDTO],
    event: EventDTO,
    participations: EnrollmentParticipationRepositoryProtocol,
) -> int:
    # Count unique users who hold at least one seat (confirmed or offered)
    return len(
        participations.occupying_user_ids(
            user_ids=[u.pk for u in users], event_id=event.pk
        )
    )


def can_enroll_users(
    *,
    users: list[UserDTO],
    event: EventDTO,
    virtual_config: VirtualEnrollmentConfig,
    users_to_enroll: list[UserDTO],
    participations: EnrollmentParticipationRepositoryProtocol,
) -> bool:
    # Get currently enrolled users (CONFIRMED + OFFERED both hold a slot)
    currently_enrolled = participations.occupying_user_ids(
        user_ids=[u.pk for u in users], event_id=event.pk
    )

    # Add new users to enroll
    users_to_enroll_ids = {u.pk for u in users_to_enroll}
    total_enrolled = currently_enrolled | users_to_enroll_ids

    return len(total_enrolled) <= virtual_config.allowed_slots


def get_vc_available_slots(
    *,
    users: list[UserDTO],
    event: EventDTO,
    virtual_config: VirtualEnrollmentConfig,
    participations: EnrollmentParticipationRepositoryProtocol,
) -> int:
    return max(
        0,
        virtual_config.allowed_slots
        - get_used_slots(users=users, event=event, participations=participations),
    )


class EnrollmentService(EnrollmentServiceProtocol):
    def __init__(
        self,
        *,
        transaction: TransactionProtocol,
        repos: EnrollmentRepos,
        membership_check_interval: int,
    ) -> None:
        self._transaction = transaction
        self._users = repos.users
        self._anonymous_users = repos.anonymous_users
        self._enrollment_configs = repos.enrollment_configs
        self._participations = repos.participations
        self._ticket_api = repos.ticket_api
        self._membership_check_interval = membership_check_interval

    def read_viewer(self, slug: str) -> UserDTO:
        return self._users.read(slug)

    def read_users(self, pks: list[int]) -> list[UserDTO]:
        return self._users.read_by_ids(pks)

    def virtual_config(
        self, *, event: EventDTO, user_email: str
    ) -> VirtualEnrollmentConfig | None:
        return get_user_enrollment_config(
            event=event,
            user_email=user_email,
            enrollment_config_repo=self._enrollment_configs,
            ticket_api=self._ticket_api,
            check_interval_minutes=self._membership_check_interval,
        )

    def has_slot_access(self, *, event: EventDTO, user_email: str) -> bool:
        # On a restricted event a member's seat spends that member's own
        # allowance, so a member without slots cannot be seated by the leader.
        if not user_email:
            return False
        config = self.virtual_config(event=event, user_email=user_email)
        return bool(config and config.allowed_slots)

    def can_enroll_users(
        self,
        *,
        users: list[UserDTO],
        event: EventDTO,
        virtual_config: VirtualEnrollmentConfig,
        users_to_enroll: list[UserDTO],
    ) -> bool:
        return can_enroll_users(
            users=users,
            event=event,
            virtual_config=virtual_config,
            users_to_enroll=users_to_enroll,
            participations=self._participations,
        )

    def get_used_slots(self, *, users: list[UserDTO], event: EventDTO) -> int:
        return get_used_slots(
            users=users, event=event, participations=self._participations
        )

    def get_vc_available_slots(
        self,
        *,
        users: list[UserDTO],
        event: EventDTO,
        virtual_config: VirtualEnrollmentConfig,
    ) -> int:
        return get_vc_available_slots(
            users=users,
            event=event,
            virtual_config=virtual_config,
            participations=self._participations,
        )

    def create_guests(
        self,
        *,
        session_id: int,
        count: int,
        party_id: int | None,
        enrolled_by_id: int,
        viewer_name: str,
    ) -> None:
        # Runs as a savepoint inside the enrollment batch transaction, after
        # the per-user requests, with the session row locked by the caller.
        with self._transaction.atomic():
            for _ in range(count):
                user_data = build_anonymous_user(
                    f"guest-{token_urlsafe(8).lower()}", name=f"{viewer_name} +1"
                )
                self._anonymous_users.create(user_data)
                guest = self._anonymous_users.read(user_data["slug"])
                self._participations.create_confirmed(
                    GuestSeatData(
                        session_id=session_id,
                        user_id=guest.pk,
                        party_id=party_id,
                        enrolled_by_id=enrolled_by_id,
                    )
                )
