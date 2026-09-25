from http import HTTPStatus
from urllib.parse import urlencode

from django.core import signing
from django.urls import reverse

from tests.integration.utils import assert_response

REDIRECT = "http://testserver/crowd/auth/do/logout/redirect"


class TestLogoutActionView:
    URL = reverse("web:crowd:auth:logout")

    def test_ends_authkit_session(self, authenticated_client):
        session = authenticated_client.session
        session["workos_session_id"] = "session_01"
        session.save()

        response = authenticated_client.get(self.URL)

        query = urlencode({"session_id": "session_01", "return_to": REDIRECT})
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[],
            url=f"https://api.workos.com/user_management/sessions/logout?{query}",
        )
        cookie = response.cookies["logout_target"]
        assert signing.loads(cookie.value, salt="logout_target") == {
            "last_domain": "testserver",
            "redirect_to": "/",
        }
        assert cookie["httponly"]
        assert "_auth_user_id" not in authenticated_client.session

    def test_session_from_before_workos_skips_the_hop(self, authenticated_client):
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[],
            url=f"{REDIRECT}?last_domain=testserver&redirect_to=%2F",
        )
        assert "_auth_user_id" not in authenticated_client.session
