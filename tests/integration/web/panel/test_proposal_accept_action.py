"""Integration tests for /panel/event/<slug>/proposals/<proposal_id>/do/accept."""

from datetime import UTC, datetime
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from tests.integration.conftest import AgendaItemFactory, EventFactory, SpaceFactory
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_login_required,
    assert_not_a_manager,
    assert_proposal_not_found,
    make_proposal,
)


class TestProposalAcceptActionView:
    """Tests for POST /panel/event/<slug>/proposals/<proposal_id>/do/accept."""

    @staticmethod
    def get_url(event, proposal_id):
        return reverse(
            "panel:proposal-accept",
            kwargs={"slug": event.slug, "proposal_id": proposal_id},
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        session = make_proposal(event)
        url = self.get_url(event, session.pk)

        response = client.post(url)

        assert_login_required(response, url)

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        session = make_proposal(event)

        response = authenticated_client.post(self.get_url(event, session.pk))

        assert_not_a_manager(response)

    def test_post_accepts_session_and_redirects(self, panel_client, event):
        session = make_proposal(event)

        response = panel_client.post(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal accepted.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert session.status == "accepted"

    def test_post_accepts_session_already_on_hold(self, panel_client, event):
        session = make_proposal(event, status="on_hold")

        response = panel_client.post(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal accepted.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert session.status == "accepted"

    def test_post_accepts_scheduled_session(self, panel_client, event):
        session = make_proposal(event, status="pending")
        AgendaItemFactory(
            session=session,
            space=SpaceFactory(event=event),
            start_time=datetime(2026, 7, 1, 18, 0, tzinfo=UTC),
            end_time=datetime(2026, 7, 1, 20, 0, tzinfo=UTC),
        )

        response = panel_client.post(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal accepted.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert session.status == "accepted"

    def test_post_redirects_when_proposal_not_found(self, panel_client, event):
        url = self.get_url(event, 99999)

        response = panel_client.post(url)

        assert_proposal_not_found(response, event)

    def test_post_redirects_when_proposal_belongs_to_different_event(
        self, panel_client, sphere, event
    ):
        other_event = EventFactory(sphere=sphere)
        session = make_proposal(other_event)

        response = panel_client.post(self.get_url(event, session.pk))

        assert_proposal_not_found(response, event)
        session.refresh_from_db()
        assert session.status == "pending"
