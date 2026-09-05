from datetime import UTC, datetime
from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import AgendaItem, ProposalCategory, Session
from tests.integration.conftest import AgendaItemFactory, SpaceFactory, UserFactory
from tests.integration.utils import assert_response


def _event_url(slug):
    return reverse("web:chronology:event", kwargs={"slug": slug})


def _withdraw_url(event_slug, session_id):
    return reverse(
        "web:chronology:session-claim-withdraw",
        kwargs={"event_slug": event_slug, "session_id": session_id},
    )


class TestSessionClaimWithdrawActionView:
    """The claim's own author taking it back off the programme."""

    @pytest.fixture(name="claim")
    def claim_fixture(self, event, active_user):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            event=event,
            category=category,
            presenter=active_user,
            display_name="Walk Up",
            title="Corridor Game",
            slug="corridor-game",
            participants_limit=5,
            status="pending",
            is_impromptu=True,
        )
        AgendaItemFactory(
            session=session,
            space=SpaceFactory(event=event),
            start_time=datetime(2026, 7, 1, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 7, 1, 20, 0, tzinfo=UTC),
        )
        return session

    def test_the_author_frees_the_spot_again(self, authenticated_client, event, claim):
        response = authenticated_client.post(_withdraw_url(event.slug, claim.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Claim withdrawn. The spot is free again.")],
            url=_event_url(event.slug),
        )
        claim.refresh_from_db()
        assert claim.status == "rejected"
        assert not AgendaItem.objects.filter(session=claim).exists()

    def test_somebody_elses_claim_is_refused(
        self, authenticated_client, event, claim, sphere
    ):
        claim.presenter = UserFactory()
        claim.save(update_fields=["presenter"])

        response = authenticated_client.post(_withdraw_url(event.slug, claim.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "This claim is not yours to withdraw.")],
            url=_event_url(event.slug),
        )
        claim.refresh_from_db()
        assert claim.status == "pending"
        assert AgendaItem.objects.filter(session=claim).exists()

    def test_an_ordinary_session_is_not_withdrawable(
        self, authenticated_client, event, claim
    ):
        claim.is_impromptu = False
        claim.save(update_fields=["is_impromptu"])

        response = authenticated_client.post(_withdraw_url(event.slug, claim.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "There is no claim here to withdraw.")],
            url=_event_url(event.slug),
        )
        assert AgendaItem.objects.filter(session=claim).exists()

    def test_an_anonymous_visitor_is_sent_to_log_in(self, client, event, claim):
        url = _withdraw_url(event.slug, claim.pk)

        response = client.post(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )
        assert AgendaItem.objects.filter(session=claim).exists()
