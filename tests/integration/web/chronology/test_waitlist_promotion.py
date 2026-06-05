from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.core.management import call_command
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    DomainEnrollmentConfig,
    Notification,
    SessionParticipation,
    SessionParticipationStatus,
    UserEnrollmentConfig,
)
from ludamus.inits.services import Services
from ludamus.inits.transaction import DjangoTransaction
from ludamus.links.db.django.enrollment import ParticipationPromotionRepository
from ludamus.pacts.legacy import NotificationKind, PromotionMode
from tests.integration.conftest import ProposalCategoryFactory, UserFactory
from tests.integration.utils import assert_response


def _service():
    return Services().waitlist_promotion


@pytest.mark.usefixtures("enrollment_config", "agenda_item")
class TestFillFreedSeats:
    def test_auto_promotes_waiter_and_notifies(self, session, waiter, mailoutbox):
        session.participants_limit = 1
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        result = _service().fill_freed_seats(session_id=session.pk)

        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.CONFIRMED.value
        assert result.promoted == [participation.pk]
        assert Notification.objects.filter(
            recipient=waiter, kind=NotificationKind.WAITLIST_PROMOTED.value
        ).exists()
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == ["waiter@example.com"]

    def test_offer_mode_holds_seat_and_notifies(
        self, session, event, waiter, mailoutbox
    ):
        session.participants_limit = 1
        session.category = ProposalCategoryFactory(
            event=event, promotion_mode=PromotionMode.OFFER_CLAIM.value
        )
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        result = _service().fill_freed_seats(session_id=session.pk)

        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.OFFERED.value
        assert participation.claim_token
        assert participation.offer_expires_at is not None
        assert result.offered == [participation.pk]
        assert Notification.objects.filter(
            recipient=waiter, kind=NotificationKind.WAITLIST_OFFER.value
        ).exists()
        assert len(mailoutbox) == 1

    def test_offered_seat_is_held_not_offered_twice(self, session, event, waiter):
        session.participants_limit = 1
        session.category = ProposalCategoryFactory(
            event=event, promotion_mode=PromotionMode.OFFER_CLAIM.value
        )
        session.save()
        other = UserFactory(username="other", email="other@example.com")
        SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )
        second = SessionParticipation.objects.create(
            session=session, user=other, status=SessionParticipationStatus.WAITING
        )

        _service().fill_freed_seats(session_id=session.pk)
        # The single seat is now held by the first offer; a re-run is a no-op.
        result = _service().fill_freed_seats(session_id=session.pk)

        second.refresh_from_db()
        assert second.status == SessionParticipationStatus.WAITING.value
        assert not result.offered

    def test_promotes_within_membership_allowance(
        self, session, waiter, enrollment_config
    ):
        # Stored user + domain configs exercise the membership-slot computation.
        UserEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            user_email=waiter.email,
            allowed_slots=5,
        )
        DomainEnrollmentConfig.objects.create(
            enrollment_config=enrollment_config,
            domain=waiter.email.split("@")[1],
            allowed_slots_per_user=2,
        )
        session.participants_limit = 1
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        result = _service().fill_freed_seats(session_id=session.pk)

        assert result.promoted == [participation.pk]
        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.CONFIRMED.value

    def test_promotes_emailless_waiter_without_membership_limit(self, session):
        emailless = UserFactory(username="no-email", email="")
        session.participants_limit = 1
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=emailless, status=SessionParticipationStatus.WAITING
        )

        result = _service().fill_freed_seats(session_id=session.pk)

        assert result.promoted == [participation.pk]
        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.CONFIRMED.value


@pytest.mark.usefixtures("enrollment_config", "agenda_item")
class TestOfferClaimAndExpiry:
    def _offer(self, session, event, waiter):
        session.participants_limit = 1
        session.category = ProposalCategoryFactory(
            event=event, promotion_mode=PromotionMode.OFFER_CLAIM.value
        )
        session.save()
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )
        _service().fill_freed_seats(session_id=session.pk)
        participation.refresh_from_db()
        return participation

    def test_claim_view_confirms_party(self, client, session, event, waiter):
        participation = self._offer(session, event, waiter)

        response = client.post(
            reverse(
                "web:chronology:offer-claim",
                kwargs={"token": participation.claim_token},
            )
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    "Spot claimed — you are now confirmed for this session.",
                )
            ],
            url=reverse("web:chronology:event", kwargs={"slug": event.slug}),
        )
        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.CONFIRMED.value
        assert participation.claimed_at is not None

    def test_claim_view_get_shows_offer(self, client, session, event, waiter):
        participation = self._offer(session, event, waiter)

        response = client.get(
            reverse(
                "web:chronology:offer-claim",
                kwargs={"token": participation.claim_token},
            )
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/offer_claim.html",
            context_data=ANY,
        )

    def test_claim_view_get_unknown_token_redirects(self, client):
        response = client.get(
            reverse("web:chronology:offer-claim", kwargs={"token": "nope"})
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.ERROR, "This offer is no longer available or has expired.")
            ],
            url=reverse("web:events"),
        )

    def test_claim_view_unknown_token_redirects(self, client):
        response = client.post(
            reverse("web:chronology:offer-claim", kwargs={"token": "nope"})
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (messages.ERROR, "This offer has expired or was already claimed.")
            ],
            url=reverse("web:events"),
        )

    def test_expire_drops_lapsed_party_and_rolls_on(
        self, session, event, waiter, mailoutbox
    ):
        participation = self._offer(session, event, waiter)
        # Force the offer past its deadline.
        participation.offer_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        participation.save()
        next_user = UserFactory(username="next", email="next@example.com")
        next_participation = SessionParticipation.objects.create(
            session=session, user=next_user, status=SessionParticipationStatus.WAITING
        )

        _service().expire_offer(participation_id=participation.pk)

        assert not SessionParticipation.objects.filter(pk=participation.pk).exists()
        next_participation.refresh_from_db()
        # AUTO is not set here (still OFFER_CLAIM), so the next waiter is offered.
        assert next_participation.status == SessionParticipationStatus.OFFERED.value
        assert any(
            m.subject.startswith("Your offer") or "expired" in m.subject.lower()
            for m in mailoutbox
        )

    def test_expire_offers_command_sweeps_lapsed_offers(self, session, event, waiter):
        participation = self._offer(session, event, waiter)
        participation.offer_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        participation.save()
        next_user = UserFactory(username="cmd-next", email="cmd-next@example.com")
        next_participation = SessionParticipation.objects.create(
            session=session, user=next_user, status=SessionParticipationStatus.WAITING
        )

        call_command("expire_offers")

        assert not SessionParticipation.objects.filter(pk=participation.pk).exists()
        next_participation.refresh_from_db()
        assert next_participation.status == SessionParticipationStatus.OFFERED.value

    def test_expire_offers_command_dedups_party_by_token(self, session, waiter):
        # A party shares one claim_token; the sweep must expire it once, not once
        # per member, so the second row with the same token is skipped.
        lapsed = datetime.now(UTC) - timedelta(minutes=1)
        other = UserFactory(username="party-2", email="party-2@example.com")
        first = SessionParticipation.objects.create(
            session=session,
            user=waiter,
            status=SessionParticipationStatus.OFFERED,
            claim_token="shared-token",
            offer_expires_at=lapsed,
        )
        second = SessionParticipation.objects.create(
            session=session,
            user=other,
            status=SessionParticipationStatus.OFFERED,
            claim_token="shared-token",
            offer_expires_at=lapsed,
        )

        call_command("expire_offers")

        assert not SessionParticipation.objects.filter(pk=first.pk).exists()
        assert not SessionParticipation.objects.filter(pk=second.pk).exists()


@pytest.mark.usefixtures("enrollment_config", "agenda_item")
class TestPromotionRepositoryEdges:
    def test_lock_and_read_state_missing_session_returns_none(self):
        with DjangoTransaction().atomic():
            assert (
                ParticipationPromotionRepository().lock_and_read_state(9_999_999)
                is None
            )

    def test_reads_return_none_for_non_offered_participations(self, session, waiter):
        confirmed = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.CONFIRMED
        )
        repo = ParticipationPromotionRepository()
        with DjangoTransaction().atomic():
            assert repo.read_offer_by_participation(confirmed.pk) is None
            assert repo.read_offer_by_participation(9_999_999) is None
            assert repo.read_offer_by_token("no-such-token") is None
