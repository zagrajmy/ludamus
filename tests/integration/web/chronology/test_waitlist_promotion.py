from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    Notification,
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.inits.services import Services
from ludamus.pacts.legacy import NotificationKind, PromotionMode
from tests.integration.conftest import ProposalCategoryFactory, UserFactory


def _service():
    return Services().waitlist_promotion


@pytest.mark.usefixtures("enrollment_config", "agenda_item")
class TestFillFreedSeats:
    def test_auto_promotes_waiter_and_notifies(
        self, session, waiter, mailoutbox
    ):
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

    def test_offered_seat_is_held_not_offered_twice(
        self, session, event, waiter
    ):
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

    def test_claim_view_confirms_party(
        self, client, session, event, waiter
    ):
        participation = self._offer(session, event, waiter)

        response = client.post(
            reverse(
                "web:chronology:offer-claim",
                kwargs={"token": participation.claim_token},
            )
        )

        assert_url = reverse("web:chronology:event", kwargs={"slug": event.slug})
        assert response.status_code == HTTPStatus.FOUND
        assert response.url == assert_url
        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.CONFIRMED.value
        assert participation.claimed_at is not None

    def test_claim_view_get_shows_offer(
        self, client, session, event, waiter
    ):
        participation = self._offer(session, event, waiter)

        response = client.get(
            reverse(
                "web:chronology:offer-claim",
                kwargs={"token": participation.claim_token},
            )
        )

        assert response.status_code == HTTPStatus.OK
        assert response.template_name == "chronology/offer_claim.html"

    def test_claim_view_unknown_token_redirects(self, client):
        response = client.post(
            reverse("web:chronology:offer-claim", kwargs={"token": "nope"})
        )

        assert response.status_code == HTTPStatus.FOUND
        assert response.url == reverse("web:events")

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
