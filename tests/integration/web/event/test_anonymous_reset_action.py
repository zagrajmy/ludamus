from http import HTTPStatus

from django.urls import reverse

from tests.integration.utils import assert_response


class TestAnonymousResetActionView:
    URL = reverse("web:chronology:anonymous-reset")

    def test_no_data(self, client):
        response = client.get(self.URL)

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))
        assert client.session.get("anonymous_user_code") is None
        assert client.session.get("anonymous_enrollment_active") is None
        assert client.session.get("anonymous_event_id") is None
        assert client.session.get("anonymous_site_id") is None

    def test_no_event(self, client):
        session = client.session
        session["anonymous_event_id"] = 123
        session.save()

        response = client.get(self.URL)

        assert_response(response, HTTPStatus.FOUND, url=reverse("web:index"))
        assert client.session.get("anonymous_user_code") is None
        assert client.session.get("anonymous_enrollment_active") is None
        assert client.session.get("anonymous_event_id") is None
        assert client.session.get("anonymous_site_id") is None

    def test_event(self, client, event):
        session = client.session
        session["anonymous_event_id"] = event.id
        session.save()

        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse(
                "web:chronology:event-anonymous-activate",
                kwargs={"event_slug": event.slug},
            ),
        )
        assert client.session.get("anonymous_user_code") is None
        assert client.session.get("anonymous_enrollment_active") is None
        assert client.session.get("anonymous_event_id") is None
        assert client.session.get("anonymous_site_id") is None
