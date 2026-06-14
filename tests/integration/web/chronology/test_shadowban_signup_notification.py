from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.adapters.db.django.models import Notification
from ludamus.pacts.legacy import NotificationKind
from tests.integration.conftest import (
    AgendaItemFactory,
    SessionFactory,
    SpaceFactory,
    UserFactory,
)


def _enroll_url(session_id: int) -> str:
    return reverse(
        "web:chronology:session-enrollment", kwargs={"session_id": session_id}
    )


@pytest.mark.usefixtures("enrollment_config")
class TestShadowbanSignupNotification:
    def test_banner_emailed_when_shadowbanned_player_joins_event(
        self, authenticated_client, agenda_item, active_user, event, space, mailoutbox
    ):
        # A banner runs a session in the event and shadowbanned the player.
        banner = UserFactory(username="gm", email="gm@example.com", name="Game Master")
        banner_session = agenda_item.session
        banner_session.presenter = banner
        banner_session.save()
        banner.shadowbanned.add(active_user)
        # The player joins a *different* session in the same event.
        host = UserFactory(username="host", email="host@example.com", name="Host")
        joined_session = SessionFactory(
            sphere=event.sphere, presenter=host, participants_limit=10, min_age=0
        )
        AgendaItemFactory(session=joined_session, space=SpaceFactory(area=space.area))

        response = authenticated_client.post(
            _enroll_url(joined_session.pk), data={f"user_{active_user.id}": "enroll"}
        )

        assert response.status_code == HTTPStatus.FOUND
        assert Notification.objects.filter(
            recipient=banner, kind=NotificationKind.SHADOWBANNED_SIGNUP.value
        ).exists()
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == ["gm@example.com"]
        assert "Test User" in mailoutbox[0].body

    def test_no_email_when_player_not_shadowbanned(
        self, authenticated_client, agenda_item, active_user, event, space, mailoutbox
    ):
        banner = UserFactory(
            username="gm2", email="gm2@example.com", name="Other Master"
        )
        banner_session = agenda_item.session
        banner_session.presenter = banner
        banner_session.save()
        host = UserFactory(username="host2", email="host2@example.com", name="Host")
        joined_session = SessionFactory(
            sphere=event.sphere, presenter=host, participants_limit=10, min_age=0
        )
        AgendaItemFactory(session=joined_session, space=SpaceFactory(area=space.area))

        response = authenticated_client.post(
            _enroll_url(joined_session.pk), data={f"user_{active_user.id}": "enroll"}
        )

        assert response.status_code == HTTPStatus.FOUND
        assert not Notification.objects.filter(
            kind=NotificationKind.SHADOWBANNED_SIGNUP.value
        ).exists()
        assert not mailoutbox
