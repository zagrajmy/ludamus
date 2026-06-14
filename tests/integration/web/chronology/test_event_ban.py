from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    EventBan,
    SessionParticipation,
    SessionParticipationStatus,
)
from tests.integration.conftest import UserFactory


def _event_url(slug: str) -> str:
    return reverse("web:chronology:event", kwargs={"slug": slug})


def _enroll_url(session_id: int) -> str:
    return reverse(
        "web:chronology:session-enrollment", kwargs={"session_id": session_id}
    )


@pytest.mark.usefixtures("enrollment_config")
class TestEventBanFakeFull:
    @pytest.mark.usefixtures("agenda_item")
    def test_banned_viewer_sees_sessions_as_full_with_simulacra(
        self, authenticated_client, active_user, event
    ):
        EventBan.objects.create(event=event, user=active_user)

        response = authenticated_client.get(_event_url(event.slug))
        content = response.content.decode()

        assert response.context["event_banned"] is True
        session_data = response.context["sessions"][0]
        assert session_data.is_full is True
        assert session_data.enrolled_count == session_data.effective_participants_limit
        # Simulacra participants are shown instead of real ones.
        assert "Aleksandra Nowak" in content
        # No enroll action for the banned viewer.
        assert "Enroll Now" not in content

    @pytest.mark.usefixtures("agenda_item")
    def test_unbanned_viewer_can_enroll(self, authenticated_client, event):
        response = authenticated_client.get(_event_url(event.slug))

        assert response.context["event_banned"] is False
        assert "Aleksandra Nowak" not in response.content.decode()

    def test_banned_viewer_enroll_post_is_blocked(
        self, authenticated_client, agenda_item, active_user, event
    ):
        EventBan.objects.create(event=event, user=active_user)

        response = authenticated_client.post(
            _enroll_url(agenda_item.session.pk),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert response.status_code == HTTPStatus.FOUND
        assert not SessionParticipation.objects.filter(
            user=active_user, session=agenda_item.session
        ).exists()

    def test_banned_viewer_enroll_get_redirects_to_event(
        self, authenticated_client, agenda_item, active_user, event
    ):
        EventBan.objects.create(event=event, user=active_user)

        response = authenticated_client.get(_enroll_url(agenda_item.session.pk))

        assert response.status_code == HTTPStatus.FOUND
        assert response.url == _event_url(event.slug)

    def test_real_participants_hidden_from_banned_viewer(
        self, authenticated_client, agenda_item, active_user, event
    ):
        real = UserFactory(
            username="real", email="real@example.com", name="Real Person"
        )
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=real,
            status=SessionParticipationStatus.CONFIRMED.value,
        )
        EventBan.objects.create(event=event, user=active_user)

        content = authenticated_client.get(_event_url(event.slug)).content.decode()

        assert "Real Person" not in content
