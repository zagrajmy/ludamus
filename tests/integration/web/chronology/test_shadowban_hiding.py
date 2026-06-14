from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import SessionParticipation
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response


def _event_url(slug: str) -> str:
    return reverse("web:chronology:event", kwargs={"slug": slug})


def _enroll_url(session_id: int) -> str:
    return reverse(
        "web:chronology:session-enrollment", kwargs={"session_id": session_id}
    )


class TestShadowbanHidesSessions:
    def test_event_page_hides_banner_sessions_from_shadowbanned_player(
        self, authenticated_client, agenda_item, active_user, event
    ):
        banner = UserFactory(username="gm", email="gm@example.com", name="GM")
        session = agenda_item.session
        session.presenter = banner
        session.title = "Hidden Game"
        session.display_name = "Hidden Game"
        session.save()
        banner.shadowbanned.add(active_user)

        response = authenticated_client.get(_event_url(event.slug))

        assert response.status_code == HTTPStatus.OK
        assert response.context["sessions"] == []
        assert "Hidden Game" not in response.content.decode()

    def test_event_page_shows_banner_sessions_to_other_users(
        self, agenda_item, event, client
    ):
        session = agenda_item.session
        session.title = "Visible Game"
        session.display_name = "Visible Game"
        session.save()

        response = client.get(_event_url(event.slug))

        assert response.status_code == HTTPStatus.OK
        assert "Visible Game" in response.content.decode()

    def test_enroll_page_redirects_shadowbanned_player(
        self, authenticated_client, agenda_item, active_user
    ):
        banner = UserFactory(username="gm2", email="gm2@example.com", name="GM")
        session = agenda_item.session
        session.presenter = banner
        session.save()
        banner.shadowbanned.add(active_user)

        response = authenticated_client.get(_enroll_url(session.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session not found.")],
            url="/",
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_enroll_post_blocked_for_shadowbanned_player(
        self, authenticated_client, agenda_item, active_user
    ):
        banner = UserFactory(username="gm3", email="gm3@example.com", name="GM")
        session = agenda_item.session
        session.presenter = banner
        session.save()
        banner.shadowbanned.add(active_user)

        response = authenticated_client.post(
            _enroll_url(session.pk), data={f"user_{active_user.id}": "enroll"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Session not found.")],
            url="/",
        )
        assert not SessionParticipation.objects.filter(
            user=active_user, session=session
        ).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_shadowbanned_connected_user_not_seated(
        self, authenticated_client, agenda_item, connected_user
    ):
        # The manager is not banned (so the guard passes), but their connected
        # sub-user is — and must not get a seat in the banner's session.
        banner = UserFactory(username="gm4", email="gm4@example.com", name="GM")
        session = agenda_item.session
        session.presenter = banner
        session.save()
        banner.shadowbanned.add(connected_user)

        response = authenticated_client.post(
            _enroll_url(session.pk), data={f"user_{connected_user.id}": "enroll"}
        )

        assert response.status_code == HTTPStatus.FOUND
        assert not SessionParticipation.objects.filter(
            user=connected_user, session=session
        ).exists()
