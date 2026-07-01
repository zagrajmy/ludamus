"""Integration tests for /panel/event/<slug>/proposals/<proposal_id>/do/accept."""

from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import ProposalCategory, Session
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _make_session(event, **kwargs):
    category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
    defaults = {
        "event": event,
        "category": category,
        "presenter": None,
        "display_name": "Test Host",
        "title": "Test Session",
        "slug": "test-session",
        "participants_limit": 5,
        "status": "pending",
    }
    defaults.update(kwargs)
    return Session.objects.create(**defaults)


class TestProposalAcceptActionView:
    """Tests for POST /panel/event/<slug>/proposals/<proposal_id>/do/accept."""

    @staticmethod
    def get_url(event, proposal_id):
        return reverse(
            "panel:proposal-accept",
            kwargs={"slug": event.slug, "proposal_id": proposal_id},
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        session = _make_session(event)
        url = self.get_url(event, session.pk)

        response = client.post(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        session = _make_session(event)

        response = authenticated_client.post(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_post_accepts_session_and_redirects(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event)

        response = authenticated_client.post(self.get_url(event, session.pk))

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

    def test_post_accepts_session_already_on_hold(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event, status="on_hold")

        response = authenticated_client.post(self.get_url(event, session.pk))

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

    def test_post_redirects_when_proposal_not_found(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = self.get_url(event, 99999)

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Proposal not found.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )

    def test_post_redirects_when_proposal_belongs_to_different_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere)
        session = _make_session(other_event)

        response = authenticated_client.post(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Proposal not found.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )
        session.refresh_from_db()
        assert session.status == "pending"
