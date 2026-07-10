from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    Notification,
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.pacts.legacy import NotificationKind
from tests.integration.conftest import (
    AgendaItemFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SpaceFactory,
    UserFactory,
)


def _enroll_url(session_id: int, event_slug: str) -> str:
    return reverse(
        "web:chronology:session-enrollment",
        kwargs={"event_slug": event_slug, "session_id": session_id},
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
            event=event, presenter=host, participants_limit=10, min_age=0
        )
        AgendaItemFactory(session=joined_session, space=SpaceFactory(event=space.event))

        response = authenticated_client.post(
            _enroll_url(joined_session.pk, joined_session.event.slug),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert response.status_code == HTTPStatus.FOUND
        assert Notification.objects.filter(
            recipient=banner, kind=NotificationKind.SHADOWBANNED_SIGNUP.value
        ).exists()
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == ["gm@example.com"]
        assert "Test User" in mailoutbox[0].body

    def test_reconfirming_existing_signup_does_not_renotify(
        self, authenticated_client, agenda_item, active_user, event, space, mailoutbox
    ):
        # Re-submitting enroll for an already-existing participation is not a
        # fresh signup, so the banner must not be alerted again.
        banner = UserFactory(username="gm3", email="gm3@example.com", name="GM")
        banner_session = agenda_item.session
        banner_session.presenter = banner
        banner_session.save()
        banner.shadowbanned.add(active_user)
        host = UserFactory(username="host3", email="host3@example.com", name="Host")
        joined_session = SessionFactory(
            event=event, presenter=host, participants_limit=10, min_age=0
        )
        AgendaItemFactory(session=joined_session, space=SpaceFactory(event=space.event))
        # Already on the waiting list -> promoting to enrolled is not a fresh
        # signup, so no new alert.
        SessionParticipation.objects.create(
            session=joined_session,
            user=active_user,
            status=SessionParticipationStatus.WAITING.value,
        )

        response = authenticated_client.post(
            _enroll_url(joined_session.pk, joined_session.event.slug),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert response.status_code == HTTPStatus.FOUND
        assert not Notification.objects.filter(
            kind=NotificationKind.SHADOWBANNED_SIGNUP.value
        ).exists()
        assert not mailoutbox

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
            event=event, presenter=host, participants_limit=10, min_age=0
        )
        AgendaItemFactory(session=joined_session, space=SpaceFactory(event=space.event))

        response = authenticated_client.post(
            _enroll_url(joined_session.pk, joined_session.event.slug),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert response.status_code == HTTPStatus.FOUND
        assert not Notification.objects.filter(
            kind=NotificationKind.SHADOWBANNED_SIGNUP.value
        ).exists()
        assert not mailoutbox

    def test_unscheduled_banner_not_notified(
        self, authenticated_client, agenda_item, active_user, event, mailoutbox
    ):
        # A banner whose only session in the event is unscheduled (no agenda
        # item) is not "on the event" and is not notified.
        banner = UserFactory(username="gm5", email="gm5@example.com", name="GM")
        SessionFactory(
            category=ProposalCategoryFactory(event=event),
            presenter=banner,
            participants_limit=10,
            min_age=0,
            status="pending",
        )
        banner.shadowbanned.add(active_user)
        # The player joins a scheduled session run by someone else.
        host = UserFactory(username="host3", email="host3@example.com", name="Host")
        agenda_item.session.presenter = host
        agenda_item.session.save()

        response = authenticated_client.post(
            _enroll_url(agenda_item.session.pk, agenda_item.session.event.slug),
            data={f"user_{active_user.id}": "enroll"},
        )

        assert response.status_code == HTTPStatus.FOUND
        assert not Notification.objects.filter(
            recipient=banner, kind=NotificationKind.SHADOWBANNED_SIGNUP.value
        ).exists()
        assert not mailoutbox
