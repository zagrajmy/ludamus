from unittest.mock import patch

import pytest
from workos import AuthenticationError

from ludamus.links.workos import WorkOSIdentityProvider
from ludamus.pacts.crowd import IdentityDTO, IdentityRejectedError
from tests.integration.web.crowd.workos_responses import (
    AUTHENTICATE,
    SESSION_ID,
    authenticate_response,
)


def _provider():
    return WorkOSIdentityProvider(api_key="sk_test", client_id="client_test")


class TestAuthenticate:
    @patch(AUTHENTICATE)
    def test_maps_the_workos_user(self, authenticate):
        authenticate.return_value = authenticate_response(
            "user_01ABC",
            email="jan@example.com",
            email_verified=False,
            first_name=" Jan ",
            last_name="Kowalski",
            profile_picture_url="https://img.example/jan.png",
            external_id="google-oauth2|42",
        )

        identity = _provider().authenticate("code-1")

        authenticate.assert_called_once_with(code="code-1")
        assert identity == IdentityDTO(
            provider_user_id="user_01ABC",
            email="jan@example.com",
            email_verified=False,
            name="Jan Kowalski",
            avatar_url="https://img.example/jan.png",
            legacy_id="google-oauth2|42",
            session_id=SESSION_ID,
        )

    @pytest.mark.parametrize(
        ("user", "name"),
        (
            ({"name": " Full Name ", "first_name": "First"}, "Full Name"),
            ({"first_name": "Only"}, "Only"),
            ({"last_name": "Last"}, "Last"),
            ({"first_name": " ", "last_name": None}, ""),
        ),
    )
    @patch(AUTHENTICATE)
    def test_display_name(self, authenticate, user, name):
        authenticate.return_value = authenticate_response("user_01ABC", **user)

        assert _provider().authenticate("code").name == name

    @patch(AUTHENTICATE)
    def test_rejected_code(self, authenticate):
        authenticate.side_effect = AuthenticationError("bad code", status_code=401)

        with pytest.raises(IdentityRejectedError):
            _provider().authenticate("code")

    @pytest.mark.parametrize("token", ("opaque", "a.bm90LWpzb24.c", "a.e30.c"))
    @patch(AUTHENTICATE)
    def test_access_token_without_session_is_rejected(self, authenticate, token):
        response = authenticate_response("user_01ABC")
        response.access_token = token
        authenticate.return_value = response

        with pytest.raises(IdentityRejectedError, match="rejected the login"):
            _provider().authenticate("code")


class TestUrls:
    def test_authorization_url_asks_for_sign_up(self):
        url = _provider().authorization_url(
            redirect_uri="https://site/cb", state="st", sign_up=True
        )

        assert url == (
            "https://api.workos.com/user_management/authorize?screen_hint=sign-up"
            "&provider=authkit&state=st&redirect_uri=https%3A%2F%2Fsite%2Fcb"
            "&response_type=code&client_id=client_test"
        )

    def test_logout_url(self):
        url = _provider().logout_url(session_id="session_01", return_to="https://x/")

        assert url == (
            "https://api.workos.com/user_management/sessions/logout"
            "?session_id=session_01&return_to=https%3A%2F%2Fx%2F"
        )
