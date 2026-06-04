from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ludamus.adapters.db.django.models import ProposalCategory, Session
from ludamus.pacts import EventDTO, SessionDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _base_context(event):
    return {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
        "stats": {
            "hosts_count": 0,
            "pending_proposals": 0,
            "rooms_count": 0,
            "scheduled_sessions": 0,
            "total_proposals": 0,
            "total_sessions": 0,
        },
        "active_nav": "proposals",
    }


class TestProposalDetailPageView:
    """Tests for /panel/event/<slug>/proposals/<proposal_id>/ page."""

    @staticmethod
    def get_url(event, proposal_id):
        return reverse(
            "panel:proposal-detail",
            kwargs={"slug": event.slug, "proposal_id": proposal_id},
        )

    def test_redirects_when_proposal_belongs_to_different_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere)
        category = ProposalCategory.objects.create(
            event=other_event, name="RPG", slug="rpg"
        )
        session = Session.objects.create(
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="Other Event Session",
            slug="other-session",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )
        url = self.get_url(event, session.pk)

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Proposal not found.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )

    def test_ok_when_session_has_no_presenter(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            category=category,
            presenter=None,
            display_name="Anonymous Host",
            title="Session Without Presenter",
            slug="no-presenter",
            sphere=sphere,
            participants_limit=5,
            status="pending",
        )
        url = self.get_url(event, session.pk)

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-detail.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 1,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 1,
                    "total_sessions": 1,
                },
                "proposal": SessionDTO.model_validate(session),
                "field_values": [],
                "facilitators": [],
                "presenter": None,
            },
        )

    def test_shows_cover_image(self, authenticated_client, active_user, sphere, event):
        sphere.managers.add(active_user)
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        session = Session.objects.create(
            category=category,
            presenter=active_user,
            display_name=active_user.name,
            title="Session With Cover",
            slug="with-cover",
            sphere=sphere,
            participants_limit=5,
            status="pending",
            cover_image=SimpleUploadedFile(
                "cover.png", PNG_BYTES, content_type="image/png"
            ),
        )
        url = self.get_url(event, session.pk)

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-detail.html",
            context_data=ANY,
        )
        assert session.cover_image_url.encode() in response.content
