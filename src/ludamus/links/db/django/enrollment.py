"""Repositories for waiting-list promotion (offer-and-claim).

Implements `ParticipationPromotionRepositoryProtocol`: locks a session, reports
the promotion state (seats, mode, FIFO waiters with per-member eligibility) and
applies the confirm / offer / claim / drop mutations. Membership allowance is
read from stored enrollment configs (no live ticket-API call on the promotion
path).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ludamus.adapters.db.django.models import (
    DomainEnrollmentConfig,
    Session,
    SessionParticipation,
    User,
    UserEnrollmentConfig,
    get_used_slots,
)
from ludamus.links.db.django.companions import (
    active_companions,
    sponsor_of,
    sponsors_by_member,
)
from ludamus.pacts import EventDTO
from ludamus.pacts.crowd import UserDTO
from ludamus.pacts.enrollment import (
    UNLIMITED_SLOTS,
    OfferDTO,
    PromotionStateDTO,
    WaitingParticipantDTO,
)
from ludamus.pacts.legacy import PromotionMode, SessionParticipationStatus

if TYPE_CHECKING:

    from ludamus.adapters.db.django.models import Event

_DEFAULT_OFFER_WINDOW = timedelta(hours=24)


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
        for participation in participations:
            user = participation.user
            sponsor = sponsors.get(user.pk)
            recipient = sponsor if sponsor is not None else user
            if recipient.pk not in slots_by_owner:
                slots_by_owner[recipient.pk] = self._slots_remaining(
                    recipient, event, event_dto
                )
            waiting.append(
                WaitingParticipantDTO(
                    participation_id=participation.pk,
                    user_id=user.pk,
                    sponsor_id=sponsor.pk if sponsor is not None else None,
                    full_name=user.get_full_name(),
                    email=user.email or "",
                    creation_time=participation.creation_time,
                    has_conflict=Session.objects.has_conflicts(
                        session, UserDTO.model_validate(user)
                    ),
                    owner_slots_remaining=slots_by_owner[recipient.pk],
                    recipient_user_id=recipient.pk,
                    recipient_email=recipient.email or "",
                )
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
        )

    @staticmethod
    def _slots_remaining(owner: User, event: Event, event_dto: EventDTO) -> int:
        if not owner.email:
            return UNLIMITED_SLOTS
        allowed = 0
        has_config = False
        domain = owner.email.split("@")[1] if "@" in owner.email else ""
        for config in event.get_active_enrollment_configs():
            user_config = UserEnrollmentConfig.objects.filter(
                enrollment_config=config, user_email=owner.email
            ).first()
            if user_config:
                allowed += user_config.allowed_slots
                has_config = True
            if domain:
                domain_config = DomainEnrollmentConfig.objects.filter(
                    enrollment_config=config, domain=domain
                ).first()
                if domain_config:
                    allowed += domain_config.allowed_slots_per_user
                    has_config = True
        if not has_config:
            return UNLIMITED_SLOTS
        # The owner's seat allowance covers themselves plus every login-less
        # companion they sponsor (members of parties they lead).
        companions = active_companions(owner.slug)
        members = [
            UserDTO.model_validate(owner),
            *(UserDTO.model_validate(c) for c in companions),
        ]
        return max(0, allowed - get_used_slots(members, event_dto))

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
        recipient = sponsor_of(lead.user) or lead.user
        return OfferDTO(
            session_id=lead.session_id,
            session_title=session.title,
            event_slug=event_slug,
            participant_ids=[p.pk for p in party],
            recipient_user_id=recipient.pk,
            recipient_email=recipient.email or "",
            offer_expires_at=lead.offer_expires_at or datetime.now(UTC),
        )

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
