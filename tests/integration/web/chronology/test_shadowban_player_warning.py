import pytest
from django.urls import reverse

from ludamus.links.db.django.models import (
    SessionParticipation,
    SessionParticipationStatus,
)
from tests.integration.conftest import UserFactory


def _enroll_url(session_id: int, event_slug: str) -> str:
    return reverse(
        "web:chronology:session-enrollment",
        kwargs={"event_slug": event_slug, "session_id": session_id},
    )


def _event_url(slug: str) -> str:
    return reverse("web:chronology:event", kwargs={"slug": slug})


def _confirm(session, user, status=SessionParticipationStatus.CONFIRMED):
    SessionParticipation.objects.create(session=session, user=user, status=status.value)


@pytest.mark.usefixtures("enrollment_config")
class TestPlayerShadowbanWarning:
    def test_enroll_page_warns_about_shadowbanned_participants(
        self, authenticated_client, agenda_item, active_user
    ):
        banned = UserFactory(username="bp", email="bp@example.com", name="Banned Bob")
        active_user.shadowbanned.add(banned)
        _confirm(agenda_item.session, banned)

        content = authenticated_client.get(
            _enroll_url(agenda_item.session.pk, agenda_item.session.event.slug)
        ).content.decode()

        assert "Players you shadowbanned are already signed up here" in content
        assert "Banned Bob" in content
        assert "shadowbanned on" in content
        assert "ring-danger" in content

    def test_enroll_page_no_warning_without_shadowbanned_participants(
        self, authenticated_client, agenda_item
    ):
        other = UserFactory(username="op", email="op@example.com", name="Other")
        _confirm(agenda_item.session, other)

        content = authenticated_client.get(
            _enroll_url(agenda_item.session.pk, agenda_item.session.event.slug)
        ).content.decode()

        assert "Players you shadowbanned are already signed up here" not in content

    def test_event_card_red_rings_shadowbanned_avatar(
        self, authenticated_client, agenda_item, active_user, event
    ):
        banned = UserFactory(username="bp2", email="bp2@example.com", name="Banned Two")
        active_user.shadowbanned.add(banned)
        _confirm(agenda_item.session, banned)

        content = authenticated_client.get(_event_url(event.slug)).content.decode()

        assert "ring-danger" in content
