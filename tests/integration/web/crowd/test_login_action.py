import json
from http import HTTPStatus
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from django.core.cache import cache
from django.urls import reverse

from tests.integration.utils import assert_response

STATE = "fixed-state-token"
CALLBACK = "http://testserver/crowd/auth/do/login/callback"


def _authorize_url(**params):
    query = params | {
        "provider": "authkit",
        "state": STATE,
        "redirect_uri": CALLBACK,
        "response_type": "code",
        "client_id": "client_test_workos",
    }
    return f"https://api.workos.com/user_management/authorize?{urlencode(query)}"


@pytest.fixture(name="fixed_state")
def fixed_state_fixture():
    with patch("ludamus.gates.web.django.crowd.auth.token_urlsafe", return_value=STATE):
        yield


def _cached_state():
    return json.loads(cache.get(f"oauth_state:{STATE}"))


@pytest.mark.usefixtures("fixed_state")
class TestLoginActionView:
    URL = reverse("web:crowd:auth:login")

    def test_ok_redirect(self, client):
        response = client.get(self.URL)

        assert_response(response, HTTPStatus.FOUND, url=_authorize_url())
        assert _cached_state() == {
            "redirect_to": None,
            "created_at": _cached_state()["created_at"],
        }

    def test_ok_redirect_keeps_safe_next(self, client):
        response = client.get(f"{self.URL}?next=/event/foo/")

        assert_response(response, HTTPStatus.FOUND, url=_authorize_url())
        assert _cached_state()["redirect_to"] == "/event/foo/"

    def test_ok_redirect_drops_external_next(self, client):
        response = client.get(f"{self.URL}?next=https://evil.example.com/")

        assert_response(response, HTTPStatus.FOUND, url=_authorize_url())
        assert _cached_state()["redirect_to"] is None

    def test_ok_redirect_forwards_signup_screen_hint(self, client):
        response = client.get(f"{self.URL}?screen_hint=signup")

        assert_response(
            response, HTTPStatus.FOUND, url=_authorize_url(screen_hint="sign-up")
        )

    def test_ok_redirect_drops_unknown_screen_hint(self, client):
        response = client.get(f"{self.URL}?screen_hint=deleteme")

        assert_response(response, HTTPStatus.FOUND, url=_authorize_url())

    def test_error_non_root_domain(self, client, non_root_sphere):
        response = client.get(self.URL, HTTP_HOST=non_root_sphere.site.domain)

        assert_response(
            response, HTTPStatus.FOUND, url="http://testserver/crowd/auth/do/login"
        )

    def test_error_non_root_domain_preserves_absolute_next(
        self, client, non_root_sphere
    ):
        domain = non_root_sphere.site.domain
        response = client.get(
            f"{self.URL}?next=/event/my-event/session/propose/", HTTP_HOST=domain
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=(
                "http://testserver/crowd/auth/do/login"
                f"?next=http%3A%2F%2F{domain}%2Fevent%2Fmy-event%2Fsession%2Fpropose%2F"
            ),
        )

    def test_error_non_root_domain_preserves_screen_hint(self, client, non_root_sphere):
        domain = non_root_sphere.site.domain
        response = client.get(f"{self.URL}?screen_hint=signup&next=/", HTTP_HOST=domain)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=(
                "http://testserver/crowd/auth/do/login"
                f"?next=http%3A%2F%2F{domain}%2F&screen_hint=signup"
            ),
        )

    def test_error_non_root_domain_forwards_screen_hint_without_next(
        self, client, non_root_sphere
    ):
        response = client.get(
            f"{self.URL}?screen_hint=signup", HTTP_HOST=non_root_sphere.site.domain
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="http://testserver/crowd/auth/do/login?screen_hint=signup",
        )
