"""Repositories for enrollment: waitlist promotion and anonymous flows.

`ParticipationPromotionRepository` locks a session, reports the promotion
state (seats, mode, FIFO waiters with per-member eligibility) and applies the
confirm / offer / claim / drop mutations; membership allowance is read from
stored enrollment configs (no live ticket-API call on the promotion path).
`AnonymousEnrollmentRepository` covers the code-based anonymous enrollment
reads and participation mutations.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ludamus.adapters.db.django.models import (
    DomainEnrollmentConfig,
    Event,
    Session,
    SessionParticipation,
    User,
    UserEnrollmentConfig,
)
from ludamus.links.db.django.companions import active_companions, sponsors_by_member
from ludamus.links.db.django.safety import ShadowbanRepository
from ludamus.pacts import OCCUPYING_PARTICIPATION_STATUSES, EventDTO
from ludamus.pacts.crowd import UserDTO
from ludamus.pacts.enrollment import (
    UNLIMITED_SLOTS,
    AnonymousEnrollmentRepositoryProtocol,
    AnonymousEventDTO,
    AnonymousLoadDTO,
    AnonymousSeatingDTO,
    AnonymousSessionContextDTO,
    EnrollmentParticipationRepositoryProtocol,
    OfferDTO,
    PromotionStateDTO,
    WaitingParticipantDTO,
    distinct_recipients,
)
from ludamus.pacts.legacy import (
    NotFoundError,
    PromotionMode,
    SessionParticipationStatus,
)

if TYPE_CHECKING:

    from ludamus.pacts.enrollment import GuestSeatData, HeldSeatData

_DEFAULT_OFFER_WINDOW = timedelta(hours=24)


class EnrollmentParticipationRepository(EnrollmentParticipationRepositoryProtocol):
    @staticmethod
    def occupying_user_ids(*, user_ids: list[int], event_id: int) -> set[int]:
        return set(
            SessionParticipation.objects.filter(
                status__in=OCCUPYING_PARTICIPATION_STATUSES,
                user_id__in=user_ids,
                session__event_id=event_id,
            )
            .values_list("user_id", flat=True)
            .distinct()
        )

    @staticmethod
    def create_confirmed(seat: GuestSeatData) -> None:
        SessionParticipation.objects.create(
            session_id=seat.session_id,
            user_id=seat.user_id,
            status=SessionParticipationStatus.CONFIRMED,
            party_id=seat.party_id,
            enrolled_by_id=seat.enrolled_by_id,
        )


class ParticipationPromotionRepository:
    def lock_and_read_state(self, session_id: int) -> PromotionStateDTO | None:
        try:
            # Lock only the Session row (`of="self"`): the select_related chain
            # LEFT-joins nullable relations (e.g. category) and Postgres refuses
            # FOR UPDATE on the nullable side of an outer join.
            session = (
                Session.objects.select_for_update(of=("self",))
                .select_related("category", "agenda_item", "event")
                .get(id=session_id)
            )
        except Session.DoesNotExist:
            return None
        # Promotion only applies to scheduled sessions (those with an agenda item).
        if not hasattr(session, "agenda_item"):
            return None
        event = session.event

        if (config := event.get_most_liberal_config(session)) is None:
            return None

        category = session.category
        mode = (
            PromotionMode(category.promotion_mode)
            if category is not None
            else PromotionMode.AUTO
        )
        window = (
            category.offer_claim_window
            if category is not None
            else _DEFAULT_OFFER_WINDOW
        )
        event_dto = EventDTO.model_validate(event)

        waiting: list[WaitingParticipantDTO] = []
        slots_by_owner: dict[int, int] = {}
        participations = list(
            session.session_participations.filter(
                status=SessionParticipationStatus.WAITING
            )
            .select_related("user")
            .order_by("creation_time")
        )
        sponsors = sponsors_by_member(p.user for p in participations)
        conflicted = Session.objects.conflicted_user_ids(
            session, [p.user_id for p in participations]
        )
        recipients = {
            p.user.pk: sponsors.get(p.user.pk, p.user) for p in participations
        }
        user_allowed, domain_allowed = self._config_allowances(
            event, {r.email or "" for r in recipients.values()}
        )
        for participation in participations:
            user = participation.user
            sponsor = sponsors.get(user.pk)
            recipient = recipients[user.pk]
            if recipient.pk not in slots_by_owner:
                slots_by_owner[recipient.pk] = self._slots_remaining(
                    owner=recipient,
                    event_dto=event_dto,
                    user_allowed=user_allowed,
                    domain_allowed=domain_allowed,
                )
            waiting.append(
                WaitingParticipantDTO(
                    participation_id=participation.pk,
                    user_id=user.pk,
                    party_id=participation.party_id,
                    sponsor_id=sponsor.pk if sponsor is not None else None,
                    full_name=user.get_full_name(),
                    email=user.email or "",
                    creation_time=participation.creation_time,
                    has_conflict=participation.user_id in conflicted,
                    owner_slots_remaining=slots_by_owner[recipient.pk],
                    recipient_user_id=recipient.pk,
                    recipient_email=recipient.email or "",
                )
            )

        shadowbanned_user_ids = frozenset(
            ShadowbanRepository.banned_user_ids(session.presenter_id)
            if session.presenter_id
            else ()
        )

        return PromotionStateDTO(
            session_id=session.pk,
            session_title=session.title,
            event_slug=event.slug,
            promotion_mode=mode,
            offer_claim_window=window,
            presenter_id=session.presenter_id,
            available_seats=config.get_available_slots(session),
            waiting=waiting,
            shadowbanned_user_ids=shadowbanned_user_ids,
        )

    @staticmethod
    def _config_allowances(
        event: Event, owner_emails: set[str]
    ) -> tuple[dict[str, int], dict[str, int]]:
        emails = {email for email in owner_emails if email}
        domains = {email.split("@")[1] for email in emails if "@" in email}
        configs = event.get_active_enrollment_configs()
        user_allowed: dict[str, int] = {}
        user_rows = UserEnrollmentConfig.objects.filter(
            enrollment_config__in=configs, user_email__in=emails
        ).values_list("user_email", "allowed_slots")
        for email, slots in user_rows:
            user_allowed[email] = user_allowed.get(email, 0) + slots
        domain_allowed: dict[str, int] = {}
        domain_rows = DomainEnrollmentConfig.objects.filter(
            enrollment_config__in=configs, domain__in=domains
        ).values_list("domain", "allowed_slots_per_user")
        for domain, slots in domain_rows:
            domain_allowed[domain] = domain_allowed.get(domain, 0) + slots
        return user_allowed, domain_allowed

    @staticmethod
    def _slots_remaining(
        *,
        owner: User,
        event_dto: EventDTO,
        user_allowed: dict[str, int],
        domain_allowed: dict[str, int],
    ) -> int:
        if not owner.email:
            return UNLIMITED_SLOTS
        domain = owner.email.split("@")[1] if "@" in owner.email else ""
        has_config = owner.email in user_allowed or (
            bool(domain) and domain in domain_allowed
        )
        if not has_config:
            return UNLIMITED_SLOTS
        allowed = user_allowed.get(owner.email, 0)
        if domain:
            allowed += domain_allowed.get(domain, 0)
        # The owner's seat allowance covers themselves plus every login-less
        # companion they sponsor (members of parties they lead).
        companions = active_companions(owner.slug)
        members = [
            UserDTO.model_validate(owner),
            *(UserDTO.model_validate(c) for c in companions),
        ]
        # Used slots = distinct owner/companion users holding a seat; the same
        # accounting `mills.enrollment.get_used_slots` applies at the gates.
        used = len(
            EnrollmentParticipationRepository.occupying_user_ids(
                user_ids=[member.pk for member in members], event_id=event_dto.pk
            )
        )
        return max(0, allowed - used)

    @staticmethod
    def confirm(participation_ids: list[int]) -> None:
        SessionParticipation.objects.filter(id__in=participation_ids).update(
            status=SessionParticipationStatus.CONFIRMED,
            modification_time=datetime.now(UTC),
        )

    @staticmethod
    def offer(
        participation_ids: list[int],
        *,
        offered_at: datetime,
        offer_expires_at: datetime,
        claim_token: str,
    ) -> None:
        SessionParticipation.objects.filter(id__in=participation_ids).update(
            status=SessionParticipationStatus.OFFERED,
            offered_at=offered_at,
            offer_expires_at=offer_expires_at,
            claim_token=claim_token,
            modification_time=datetime.now(UTC),
        )

    @staticmethod
    def create_offered(seat: HeldSeatData) -> int:
        participation = SessionParticipation.objects.create(
            session_id=seat.session_id,
            user_id=seat.user_id,
            party_id=seat.party_id,
            status=SessionParticipationStatus.OFFERED,
            offered_at=seat.offered_at,
            offer_expires_at=seat.offer_expires_at,
            claim_token=seat.claim_token,
        )
        return participation.pk

    @staticmethod
    def read_offer_claim_window(session_id: int) -> timedelta:
        category = (
            Session.objects.select_related("category").get(id=session_id).category
        )
        return (
            category.offer_claim_window
            if category is not None
            else _DEFAULT_OFFER_WINDOW
        )

    def read_offer_by_token(self, token: str) -> OfferDTO | None:
        identity = (
            SessionParticipation.objects.filter(
                claim_token=token, status=SessionParticipationStatus.OFFERED
            )
            .values("session_id")
            .first()
        )
        if identity is None:
            return None
        return self._read_locked_party(identity["session_id"], token)

    def read_offer_by_participation(self, participation_id: int) -> OfferDTO | None:
        try:
            participation = SessionParticipation.objects.get(id=participation_id)
        except SessionParticipation.DoesNotExist:
            return None
        if (
            participation.status != SessionParticipationStatus.OFFERED
            or not participation.claim_token
        ):
            return None
        return self._read_locked_party(
            participation.session_id, participation.claim_token
        )

    def _read_locked_party(self, session_id: int, token: str) -> OfferDTO | None:
        # Lock the party's still-OFFERED rows for the caller's transaction so
        # claim and expiry serialise; the loser re-reads an empty set and no-ops.
        party = list(
            SessionParticipation.objects.select_for_update(of=("self",))
            .filter(
                session_id=session_id,
                claim_token=token,
                status=SessionParticipationStatus.OFFERED,
            )
            .select_related("user")
            .order_by("creation_time")
        )
        if not party:
            return None
        return self._build_offer(party)

    @staticmethod
    def _build_offer(party: list[SessionParticipation]) -> OfferDTO:
        lead = party[0]
        session = Session.objects.select_related("event").get(id=lead.session_id)
        event_slug = session.event.slug
        sponsors = sponsors_by_member(p.user for p in party)
        recipients = distinct_recipients(
            (recipient.pk, recipient.email or "")
            for recipient in (sponsors.get(p.user.pk, p.user) for p in party)
        )
        return OfferDTO(
            session_id=lead.session_id,
            session_title=session.title,
            event_slug=event_slug,
            participant_ids=[p.pk for p in party],
            recipients=recipients,
            offer_expires_at=lead.offer_expires_at or datetime.now(UTC),
        )

    @staticmethod
    def list_lapsed_offers(now: datetime) -> list[int]:
        # One representative per lapsed party (the service expands to the whole
        # party from the shared claim token).
        lapsed = (
            SessionParticipation.objects.filter(
                status=SessionParticipationStatus.OFFERED, offer_expires_at__lt=now
            )
            .values_list("claim_token", "id")
            .order_by("claim_token", "id")
        )
        seen: set[str] = set()
        representatives: list[int] = []
        for claim_token, participation_id in lapsed:
            if claim_token in seen:
                continue
            seen.add(claim_token)
            representatives.append(participation_id)
        return representatives

    @staticmethod
    def mark_claimed(participation_ids: list[int], *, claimed_at: datetime) -> None:
        # Status-scoped so a racing expiry that already dropped the party cannot
        # be clobbered (and vice-versa) — only still-OFFERED rows are claimed.
        SessionParticipation.objects.filter(
            id__in=participation_ids, status=SessionParticipationStatus.OFFERED
        ).update(
            status=SessionParticipationStatus.CONFIRMED,
            claimed_at=claimed_at,
            modification_time=datetime.now(UTC),
        )

    @staticmethod
    def drop(participation_ids: list[int]) -> None:
        # A lapsed offer is terminal (Eventbrite-style): drop the rows so the
        # held seats are released and the party must rejoin to be reconsidered.
        # Status-scoped so a party already claimed by a racing winner is left be.
        SessionParticipation.objects.filter(
            id__in=participation_ids, status=SessionParticipationStatus.OFFERED
        ).delete()


class AnonymousEnrollmentRepository(AnonymousEnrollmentRepositoryProtocol):
    @staticmethod
    def read_event(event_slug: str) -> AnonymousEventDTO:
        try:
            event = Event.objects.get(slug=event_slug)
        except Event.DoesNotExist as exception:
            raise NotFoundError from exception
        return AnonymousEventDTO(
            event_id=event.pk,
            slug=event.slug,
            allows_anonymous_enrollment=any(
                config.allow_anonymous_enrollment
                for config in event.get_active_enrollment_configs()
            ),
        )

    @staticmethod
    def event_slug_by_id(event_id: int) -> str | None:
        return Event.objects.filter(pk=event_id).values_list("slug", flat=True).first()

    @staticmethod
    def read_session(
        *, session_id: int, event_slug: str, site_id: int
    ) -> AnonymousSessionContextDTO:
        try:
            session = Session.objects.select_related("event").get(
                id=session_id, event__slug=event_slug, event__sphere__site_id=site_id
            )
        except Session.DoesNotExist as exception:
            raise NotFoundError from exception
        event = session.event
        has_agenda_item = hasattr(session, "agenda_item")
        return AnonymousSessionContextDTO(
            session_id=session.pk,
            event_id=event.pk,
            event_slug=event.slug,
            has_agenda_item=has_agenda_item,
            allows_anonymous_enrollment=has_agenda_item
            and any(
                config.allow_anonymous_enrollment
                and config.is_session_eligible(session)
                for config in event.get_active_enrollment_configs()
            ),
            title=session.title,
            display_name=session.display_name,
            description=session.description,
            min_age=session.min_age,
            enrolled_count=session.enrolled_count,
            waiting_count=session.waiting_count,
            effective_participants_limit=session.effective_participants_limit,
            space_name=session.agenda_item.space.name if has_agenda_item else None,
            start_time=session.agenda_item.start_time if has_agenda_item else None,
            end_time=session.agenda_item.end_time if has_agenda_item else None,
        )

    @staticmethod
    def read_participation_status(
        *, session_id: int, user_id: int
    ) -> SessionParticipationStatus | None:
        status = (
            SessionParticipation.objects.filter(session_id=session_id, user_id=user_id)
            .values_list("status", flat=True)
            .first()
        )
        return SessionParticipationStatus(status) if status else None

    @staticmethod
    def has_conflicts(*, session_id: int, user: UserDTO) -> bool:
        session = Session.objects.get(id=session_id)
        return Session.objects.has_conflicts(session, user)

    @staticmethod
    def lock_seating(session_id: int) -> AnonymousSeatingDTO:
        session = Session.objects.select_for_update(of=("self",)).get(id=session_id)
        return AnonymousSeatingDTO(is_full=session.is_full, title=session.title)

    @staticmethod
    def create_or_confirm(*, session_id: int, user_id: int) -> None:
        participation, created = SessionParticipation.objects.get_or_create(
            session_id=session_id,
            user_id=user_id,
            defaults={"status": SessionParticipationStatus.CONFIRMED.value},
        )
        if (
            not created
            and participation.status != SessionParticipationStatus.CONFIRMED.value
        ):
            participation.status = SessionParticipationStatus.CONFIRMED.value
            participation.save()

    @staticmethod
    def create_waiting(*, session_id: int, user_id: int) -> None:
        SessionParticipation.objects.get_or_create(
            session_id=session_id,
            user_id=user_id,
            defaults={"status": SessionParticipationStatus.WAITING.value},
        )

    @staticmethod
    def delete_participation(
        *, session_id: int, user_id: int
    ) -> SessionParticipationStatus | None:
        try:
            participation = SessionParticipation.objects.get(
                session_id=session_id, user_id=user_id
            )
        except SessionParticipation.DoesNotExist:
            return None
        status = SessionParticipationStatus(participation.status)
        participation.delete()
        return status

    @staticmethod
    def first_enrollment_event(user_id: int) -> AnonymousLoadDTO | None:
        participation = (
            SessionParticipation.objects.filter(user_id=user_id)
            .select_related("session__event__sphere")
            .order_by("creation_time")
            .first()
        )
        if participation is None:
            return None
        event = participation.session.event
        return AnonymousLoadDTO(
            event_id=event.pk, event_slug=event.slug, site_id=event.sphere.site_id
        )
