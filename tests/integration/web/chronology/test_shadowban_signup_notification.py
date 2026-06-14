from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.adapters.db.django.models import Notification
from ludamus.pacts.legacy import NotificationKind
from tests.integration.conftest import UserFactory


def _enroll_url(session_id: int) -> str:
    return reverse(
        "web:chronology:session-enrollment", kwargs={"session_id": session_id}
    )


@pytest.mark.usefixtures("enrollment_config")
class TestShadowbanSignupNotification:
    def test_presenter_emailed_when_shadowbanned_player_signs_up(
        self, authenticated_client, agenda_item, active_user, mailoutbox
    ):
        presenter = UserFactory(
            username="gm", email="gm@example.com", name="Game Master"
        )
        session = agenda_item.session
        session.presenter = presenter
        session.save()
        presenter.shadowbanned.add(active_user)

        response = authenticated_client.post(
            _enroll_url(session.pk), data={f"user_{active_user.id}": "enroll"}
        )

        assert response.status_code == HTTPStatus.FOUND
        assert Notification.objects.filter(
            recipient=presenter, kind=NotificationKind.SHADOWBANNED_SIGNUP.value
        ).exists()
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == ["gm@example.com"]
        assert "Test User" in mailoutbox[0].body

    def test_no_email_when_player_not_shadowbanned(
        self, authenticated_client, agenda_item, active_user, mailoutbox
    ):
        presenter = UserFactory(
            username="gm2", email="gm2@example.com", name="Other Master"
        )
        session = agenda_item.session
        session.presenter = presenter
        session.save()

        response = authenticated_client.post(
            _enroll_url(session.pk), data={f"user_{active_user.id}": "enroll"}
        )

        assert response.status_code == HTTPStatus.FOUND
        assert not Notification.objects.filter(
            kind=NotificationKind.SHADOWBANNED_SIGNUP.value
        ).exists()
        assert mailoutbox == []
