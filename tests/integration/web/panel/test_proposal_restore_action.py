"""Integration tests for /panel/event/<slug>/proposals/<proposal_id>/do/restore."""

from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Session
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_login_required,
    assert_not_a_manager,
    assert_proposal_not_found,
    make_proposal,
)


def _make_deleted_session(event, **kwargs):
    session = make_proposal(event, **kwargs)
    session.soft_delete()
    return session


class TestProposalRestoreActionView:
    @staticmethod
    def get_url(event, proposal_id):
        return reverse(
            "panel:proposal-restore",
            kwargs={"slug": event.slug, "proposal_id": proposal_id},
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        session = _make_deleted_session(event)
        url = self.get_url(event, session.pk)

        response = client.post(url)

        assert_login_required(response, url)
        session.refresh_from_db()
        assert session.deleted_at is not None

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        session = _make_deleted_session(event)

        response = authenticated_client.post(self.get_url(event, session.pk))

        assert_not_a_manager(response)
        session.refresh_from_db()
        assert session.deleted_at is not None

    def test_post_restores_session_and_redirects(self, panel_client, event):
        session = _make_deleted_session(event)

        response = panel_client.post(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session restored.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )
        restored = Session.objects.get(pk=session.pk)
        assert restored.deleted_at is None

    def test_post_redirects_when_proposal_not_deleted(self, panel_client, event):
        session = make_proposal(event)

        response = panel_client.post(self.get_url(event, session.pk))

        assert_proposal_not_found(response, event)

    def test_post_redirects_when_proposal_belongs_to_different_event(
        self, panel_client, sphere, event
    ):
        other_event = EventFactory(sphere=sphere)
        session = _make_deleted_session(other_event)

        response = panel_client.post(self.get_url(event, session.pk))

        assert_proposal_not_found(response, event)
        session.refresh_from_db()
        assert session.deleted_at is not None

    def test_post_redirects_when_event_not_found(self, panel_client):
        url = reverse(
            "panel:proposal-restore", kwargs={"slug": "no-such-event", "proposal_id": 1}
        )

        response = panel_client.post(url)

        assert_event_not_found(response)

    def test_proposals_page_renders_recently_deleted_section(self, panel_client, event):
        pending = _make_deleted_session(event, title="Lost Adventure")
        rejected = Session.objects.create(
            category=pending.category,
            presenter=None,
            display_name="Test Host",
            title="Cancelled Quest",
            slug="cancelled-quest",
            event=event,
            participants_limit=5,
            status="rejected",
        )
        rejected.soft_delete()

        response = panel_client.get(
            reverse("panel:proposals", kwargs={"slug": event.slug})
        )

        content = response.content.decode()
        assert "Recently deleted" in content
        assert pending.title in content
        assert rejected.title in content
        assert "Pending" in content
        assert "Rejected" in content
