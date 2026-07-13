from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.adapters.db.django.models import SessionParticipation
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response


def _event_url(slug: str) -> str:
    return reverse("web:chronology:event", kwargs={"slug": slug})


def _enroll_url(session_id: int, event_slug: str) -> str:
    return reverse(
        "web:chronology:session-enrollment",
        kwargs={"event_slug": event_slug, "session_id": session_id},
    )


def _ban_viewer(agenda_item, viewer, *, username: str):
    banner = UserFactory(username=username, email=f"{username}@example.com", name="GM")
    session = agenda_item.session
    session.presenter = banner
    session.save()
    banner.shadowbanned.add(viewer)
    return session


class TestShadowbanPretendFull:
    # Intended behaviour: the banner's sessions render pretend-full, never
    # hidden — a hidden session would reveal the ban (compare the program
    # with a friend's view), a full one is deniable.
    # See docs/features/crowd/profile/shadowban.md.

    def test_event_page_shows_banner_session_as_full(
        self, authenticated_client, agenda_item, active_user, event
    ):
        session = _ban_viewer(agenda_item, active_user, username="gm")
        session.title = "Deniable Game"
        session.display_name = "Deniable Game"
        session.save()

        response = authenticated_client.get(_event_url(event.slug))

        assert response.status_code == HTTPStatus.OK
        assert "Deniable Game" in response.content.decode()
        (card,) = response.context["sessions"]
        assert card.is_full
        assert card.spots_left == 0
        assert card.enrolled_count == card.effective_participants_limit
        assert all(p.user.pk < 0 for p in card.session_participations)

    def test_event_page_untouched_for_other_users(self, agenda_item, event, client):
        session = agenda_item.session
        session.title = "Visible Game"
        session.display_name = "Visible Game"
        session.save()

        response = client.get(_event_url(event.slug))

        assert response.status_code == HTTPStatus.OK
        assert "Visible Game" in response.content.decode()
        (card,) = response.context["sessions"]
        assert not card.is_full

    def test_enroll_page_bounces_to_event_without_error(
        self, authenticated_client, agenda_item, active_user
    ):
        session = _ban_viewer(agenda_item, active_user, username="gm2")

        response = authenticated_client.get(_enroll_url(session.pk, session.event.slug))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[],
            url=_event_url(session.event.slug),
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_enroll_post_blocked_and_bounced(
        self, authenticated_client, agenda_item, active_user
    ):
        session = _ban_viewer(agenda_item, active_user, username="gm3")

        response = authenticated_client.post(
            _enroll_url(session.pk, session.event.slug),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[],
            url=_event_url(session.event.slug),
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
        session = _ban_viewer(agenda_item, connected_user, username="gm4")

        response = authenticated_client.post(
            _enroll_url(session.pk, session.event.slug),
            data={f"user_{connected_user.id}": "enroll"},
        )

        assert response.status_code == HTTPStatus.FOUND
        assert not SessionParticipation.objects.filter(
            user=connected_user, session=session
        ).exists()
