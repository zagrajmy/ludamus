"""Integration tests for /panel/event/<slug>/proposals/<proposal_id>/do/hold."""

from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_login_required,
    assert_not_a_manager,
    assert_proposal_not_found,
    assert_scheduled_proposal_refused,
    make_proposal,
    make_scheduled_proposal,
)


class TestProposalHoldActionView:
    """Tests for POST /panel/event/<slug>/proposals/<proposal_id>/do/hold."""

    @staticmethod
    def get_url(event, proposal_id):
        return reverse(
            "panel:proposal-hold",
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

    def test_post_holds_session_and_redirects(self, panel_client, event):
        session = make_proposal(event)

        response = panel_client.post(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal put on hold.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert session.status == "on_hold"

    def test_post_holds_session_already_accepted(self, panel_client, event):
        session = make_proposal(event, status="accepted")

        response = panel_client.post(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal put on hold.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert session.status == "on_hold"

    def test_post_redirects_to_index_when_event_not_found(self, panel_client):
        url = reverse(
            "panel:proposal-hold", kwargs={"slug": "nonexistent", "proposal_id": 1}
        )

        response = panel_client.post(url)

        assert_event_not_found(response)

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

    def test_post_rejects_scheduled_session(self, panel_client, event):
        session = make_scheduled_proposal(event)

        response = panel_client.post(self.get_url(event, session.pk))

        assert_scheduled_proposal_refused(response, event, session)
        session.refresh_from_db()
        assert session.status == "accepted"
