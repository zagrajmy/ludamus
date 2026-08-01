"""Integration tests for the proposal set-facilitators action."""

from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Facilitator
from ludamus.pacts import EventDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    assert_proposal_not_found,
    make_proposal,
)


def _base_context(event):
    return {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
    }


def _make_session(event, **kwargs):
    defaults = {"display_name": "Host", "participants_limit": 0}
    return make_proposal(event, **(defaults | kwargs))


class TestProposalSetFacilitatorsActionView:
    """Tests for proposal-set-facilitators POST action."""

    @staticmethod
    def get_url(event, proposal_id):
        return reverse(
            "panel:proposal-set-facilitators",
            kwargs={"slug": event.slug, "proposal_id": proposal_id},
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        session = _make_session(event)
        url = self.get_url(event, session.pk)

        response = client.post(url, data={})

        assert_login_required(response, url)

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        session = _make_session(event)

        response = authenticated_client.post(self.get_url(event, session.pk), data={})

        assert_not_a_manager(response)

    def test_post_redirects_when_event_not_found(self, panel_client):
        url = reverse(
            "panel:proposal-set-facilitators",
            kwargs={"slug": "nonexistent", "proposal_id": 1},
        )

        response = panel_client.post(url, data={})

        assert_event_not_found(response)

    def test_post_sets_facilitators_and_redirects(self, panel_client, event):
        session = _make_session(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = panel_client.post(
            self.get_url(event, session.pk), data={"facilitator_ids": [facilitator.pk]}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitators updated.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        assert session.facilitators.filter(pk=facilitator.pk).exists()

    def test_post_ignores_facilitator_from_other_event(
        self, panel_client, sphere, event
    ):
        session = _make_session(event)
        other_event = EventFactory(sphere=sphere)
        foreign_facilitator = Facilitator.objects.create(
            event=other_event, display_name="Mallory", slug="mallory", user=None
        )

        response = panel_client.post(
            self.get_url(event, session.pk),
            data={"facilitator_ids": [foreign_facilitator.pk]},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitators updated.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        assert not session.facilitators.exists()

    def test_post_clears_facilitators_when_empty(self, panel_client, event):
        session = _make_session(event)
        facilitator = Facilitator.objects.create(
            event=event, display_name="Bob", slug="bob", user=None
        )
        session.facilitators.add(facilitator)

        response = panel_client.post(self.get_url(event, session.pk), data={})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Facilitators updated.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        assert not session.facilitators.exists()

    def test_post_redirects_when_proposal_not_found(self, panel_client, event):
        response = panel_client.post(self.get_url(event, 99999), data={})

        assert_proposal_not_found(response, event)

    def test_post_redirects_when_proposal_belongs_to_different_event(
        self, panel_client, sphere, event
    ):
        other_event = EventFactory(sphere=sphere)
        session = _make_session(other_event)

        response = panel_client.post(self.get_url(event, session.pk), data={})

        assert_proposal_not_found(response, event)
