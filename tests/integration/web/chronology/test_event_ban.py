from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.links.db.django.models import (
    EventBan,
    SessionParticipation,
    SessionParticipationStatus,
)
from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response
from tests.integration.web.chronology.helpers import (
    CARDS_PER_SESSION,
    card_buckets,
    event_page_context,
    every_card,
    is_deniably_full,
    session_card,
)


def _event_url(slug: str) -> str:
    return reverse("web:chronology:event", kwargs={"slug": slug})


def _enroll_url(session_id: int, event_slug: str) -> str:
    return reverse(
        "web:chronology:session-enrollment",
        kwargs={"event_slug": event_slug, "session_id": session_id},
    )


@pytest.mark.usefixtures("enrollment_config")
class TestEventBanFakeFull:
    def test_banned_viewer_sees_sessions_as_full_with_simulacra(
        self, authenticated_client, active_user, agenda_item, event
    ):
        EventBan.objects.create(event=event, user=active_user)

        response = authenticated_client.get(_event_url(event.slug))

        # The masked card claims an open, fully booked session, so it lands in
        # the current lane and its invented seats count toward the page total.
        buckets = card_buckets(
            response, agenda_item.start_time, lane="current_hour_data"
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=_event_url(event.slug),
                event_banned=True,
                total_enrolled=10,
                has_enrollable_sessions=True,
                scheduled_count=1,
                **buckets,
            ),
            template_name=["chronology/event.html"],
        )
        cards = every_card(buckets)
        assert len(cards) == CARDS_PER_SESSION
        assert all(is_deniably_full(card) for card in cards)

    def test_unbanned_viewer_can_enroll(self, authenticated_client, agenda_item, event):
        response = authenticated_client.get(_event_url(event.slug))

        card = session_card(
            agenda_item,
            presenter=agenda_item.session.presenter,
            is_enrollment_available=True,
            can_edit=True,
        )
        assert_response(
            response,
            HTTPStatus.OK,
            context_data=event_page_context(
                event,
                url=_event_url(event.slug),
                hour_data={agenda_item.start_time: [card]},
                current_hour_data={agenda_item.start_time: [card]},
                sessions=[card],
                has_enrollable_sessions=True,
                scheduled_count=1,
            ),
            template_name=["chronology/event.html"],
        )

    def test_banned_viewer_enroll_post_is_blocked(
        self, authenticated_client, agenda_item, active_user, event
    ):
        EventBan.objects.create(event=event, user=active_user)

        response = authenticated_client.post(
            _enroll_url(agenda_item.session.pk, agenda_item.session.event.slug),
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

        response = authenticated_client.get(
            _enroll_url(agenda_item.session.pk, agenda_item.session.event.slug)
        )

        assert_response(response, HTTPStatus.FOUND, url=_event_url(event.slug))

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
