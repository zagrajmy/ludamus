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

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=response.context_data,
            template_name=["chronology/event.html"],
            contains=["Deniable Game", "Session full"],
        )
        (card,) = response.context["sessions"]
        assert card.pretend_full
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

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=response.context_data,
            template_name=["chronology/event.html"],
            contains="Visible Game",
        )
        (card,) = response.context["sessions"]
        assert not card.is_full

    @pytest.mark.usefixtures("enrollment_config")
    def test_enroll_page_renders_standard_full_state(
        self, authenticated_client, agenda_item, active_user
    ):
        session = _ban_viewer(agenda_item, active_user, username="gm2")

        response = authenticated_client.get(_enroll_url(session.pk, session.event.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data=response.context_data,
            template_name="chronology/enroll_select.html",
        )
        page_session = response.context["session"]
        assert page_session.is_full
        assert page_session.enrolled_count == page_session.effective_participants_limit
        assert page_session.waiting_count == 0

    @pytest.mark.usefixtures("enrollment_config")
    def test_enroll_post_never_seats_the_shadowbanned(
        self, authenticated_client, agenda_item, active_user
    ):
        session = _ban_viewer(agenda_item, active_user, username="gm3")

        response = authenticated_client.post(
            _enroll_url(session.pk, session.event.slug),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert response.status_code == HTTPStatus.FOUND
        assert not SessionParticipation.objects.filter(
            user=active_user, session=session
        ).exists()

    @pytest.mark.usefixtures("enrollment_config")
    def test_shadowbanned_companion_not_seated(
        self, authenticated_client, agenda_item, companion
    ):
        # The manager is not banned (so the guard passes), but their companion
        # is — and must not get a seat in the banner's session.
        session = _ban_viewer(agenda_item, companion, username="gm4")

        response = authenticated_client.post(
            _enroll_url(session.pk, session.event.slug),
            data={f"user_{companion.id}": "enroll"},
        )

        assert response.status_code == HTTPStatus.FOUND
        assert not SessionParticipation.objects.filter(
            user=companion, session=session
        ).exists()
