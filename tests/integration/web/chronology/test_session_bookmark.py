from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.adapters.db.django.models import SessionBookmark
from tests.integration.conftest import EventFactory, SessionFactory, SphereFactory


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
        assert SessionBookmark.objects.filter(
            user=active_user, session=session
        ).exists()

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
