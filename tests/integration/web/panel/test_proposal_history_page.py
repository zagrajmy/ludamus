from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import ContentChangeLog, ProposalCategory, Session
from ludamus.pacts import ContentChangeLogDTO, EventDTO
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _base_context(event):
    return {
        "current_event": EventDTO.model_validate(event),
        "events": [EventDTO.model_validate(event)],
        "is_proposal_active": False,
        "active_nav": "proposals",
    }


def _make_session(event, title, slug):
    category = ProposalCategory.objects.get_or_create(
        event=event, name="RPG", slug="rpg"
    )[0]
    return Session.objects.create(
        event=event,
        category=category,
        display_name="Host",
        title=title,
        slug=slug,
        participants_limit=5,
        status="pending",
    )


def _tab_urls(event, proposal_id):
    return {
        "details": reverse(
            "panel:proposal-detail",
            kwargs={"slug": event.slug, "proposal_id": proposal_id},
        ),
        "history": reverse(
            "panel:proposal-history",
            kwargs={"slug": event.slug, "proposal_id": proposal_id},
        ),
    }


class TestProposalHistoryPageView:
    """Tests for /panel/event/<slug>/proposals/<proposal_id>/history/ page."""

    @staticmethod
    def get_url(event, proposal_id):
        return reverse(
            "panel:proposal-history",
            kwargs={"slug": event.slug, "proposal_id": proposal_id},
        )

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event, 1)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(self.get_url(event, 1))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_redirects_when_proposal_not_found(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event, 999))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Proposal not found.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )

    def test_renders_only_this_proposals_logs(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event, "Dragon Heist", "dragon-heist")
        other = _make_session(event, "Space Opera", "space-opera")
        log = ContentChangeLog.objects.create(
            event=event,
            session=session,
            user=active_user,
            changes=[{"field": "title", "field_id": None, "old": "A", "new": "B"}],
        )
        ContentChangeLog.objects.create(
            event=event,
            session=other,
            user=active_user,
            changes=[{"field": "title", "field_id": None, "old": "C", "new": "D"}],
        )

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-history.html",
            context_data={
                **_base_context(event),
                "stats": {
                    "hosts_count": 0,
                    "pending_proposals": 2,
                    "rooms_count": 0,
                    "scheduled_sessions": 0,
                    "total_proposals": 2,
                    "total_sessions": 2,
                },
                "active_tab": "history",
                "tab_urls": _tab_urls(event, session.pk),
                "proposal_title": "Dragon Heist",
                "logs": [
                    ContentChangeLogDTO(
                        pk=log.pk,
                        event_id=event.pk,
                        session_id=session.pk,
                        session_title="Dragon Heist",
                        user_id=active_user.pk,
                        user_name=active_user.name,
                        changes=[
                            {"field": "title", "field_id": None, "old": "A", "new": "B"}
                        ],
                        creation_time=log.creation_time,
                    )
                ],
                "field_names": {},
            },
            contains=["Dragon Heist"],
        )

    def test_renders_empty_history(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event, "Dragon Heist", "dragon-heist")

        response = authenticated_client.get(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-history.html",
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
                "active_tab": "history",
                "tab_urls": _tab_urls(event, session.pk),
                "proposal_title": "Dragon Heist",
                "logs": [],
                "field_names": {},
            },
            contains="No changes recorded yet.",
        )
