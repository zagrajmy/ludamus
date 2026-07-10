from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.adapters.db.django.models import SessionBookmark
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    SessionFactory,
    SphereFactory,
    UserFactory,
)


class TestSessionBookmarkToggleView:
    URL_NAME = "web:chronology:session-bookmark"

    def _url(self, session_id: int) -> str:
        return reverse(self.URL_NAME, kwargs={"session_id": session_id})

    def test_unauthorized_when_anonymous(self, client, session):
        response = client.post(self._url(session.pk))

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.json() == {"error": "auth"}
        assert not SessionBookmark.objects.exists()

    def test_toggle_on_then_off(self, authenticated_client, active_user, session):
        response_on = authenticated_client.post(self._url(session.pk))

        assert response_on.status_code == HTTPStatus.OK
        assert response_on.json() == {"bookmarked": True}
        bookmark = SessionBookmark.objects.get(user=active_user, session=session)
        assert str(bookmark) == f"{active_user.pk} bookmarked session {session.pk}"

        response_off = authenticated_client.post(self._url(session.pk))

        assert response_off.status_code == HTTPStatus.OK
        assert response_off.json() == {"bookmarked": False}
        assert not SessionBookmark.objects.exists()

    def test_not_found_for_other_sphere_session(self, authenticated_client):
        other_event = EventFactory(sphere=SphereFactory())
        other_session = SessionFactory(event=other_event, category=None)

        response = authenticated_client.post(self._url(other_session.pk))

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.json() == {"error": "not-found"}
        assert not SessionBookmark.objects.exists()

    @pytest.mark.usefixtures("session")
    def test_not_found_for_missing_session(self, authenticated_client):
        response = authenticated_client.post(self._url(999_999))

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.json() == {"error": "not-found"}


class TestEventPageBookmarkCounts:
    URL_NAME = "web:chronology:event"

    def _url(self, slug: str) -> str:
        return reverse(self.URL_NAME, kwargs={"slug": slug})

    @pytest.fixture(autouse=True)
    def _compact_schedule(self, monkeypatch):
        monkeypatch.setattr(
            "ludamus.adapters.web.django.views.COMPACT_SCHEDULE_MIN_SESSIONS", 1
        )

    def test_anonymous_sees_count_badge_and_zero_count_renders_nothing(
        self, agenda_item, client, event, space
    ):
        SessionBookmark.objects.create(user=UserFactory(), session=agenda_item.session)
        SessionBookmark.objects.create(user=UserFactory(), session=agenda_item.session)
        AgendaItemFactory(
            session=SessionFactory(event=event, category=None), space=space
        )

        response = client.get(self._url(event.slug))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "Bookmarked by 2 people" in content
        assert content.count("Bookmarked by") == 1
        assert "bookmark-toggle" not in content

    def test_anonymous_rooms_view_shows_count_badge(self, agenda_item, client, event):
        SessionBookmark.objects.create(user=UserFactory(), session=agenda_item.session)

        response = client.get(self._url(event.slug), {"view": "rooms"})

        assert response.status_code == HTTPStatus.OK
        assert "Bookmarked by 1 person" in response.content.decode()

    def test_authenticated_toggle_shows_count_and_hides_zero(
        self, agenda_item, authenticated_client, event, space
    ):
        SessionBookmark.objects.create(user=UserFactory(), session=agenda_item.session)
        SessionBookmark.objects.create(user=UserFactory(), session=agenda_item.session)
        SessionBookmark.objects.create(user=UserFactory(), session=agenda_item.session)
        AgendaItemFactory(
            session=SessionFactory(event=event, category=None), space=space
        )

        scheduled_sessions = 2

        response = authenticated_client.get(self._url(event.slug))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert content.count("bookmark-toggle") == scheduled_sessions
        assert ">3</span>" in content
        assert "tabular-nums hidden" in content
