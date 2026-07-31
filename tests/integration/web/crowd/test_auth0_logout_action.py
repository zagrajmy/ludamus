from http import HTTPStatus
from urllib.parse import urlencode

from django.urls import reverse

from tests.integration.utils import assert_response


class TestAuth0LogoutActionView:
    URL = reverse("web:crowd:auth0:logout")

    def test_ok(self, authenticated_client, settings):
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[],
            url="https://auth0.example.com/v2/logout?"
            + urlencode(
                {
                    "returnTo": (
                        "http://testserver/crowd/auth0/do/logout/redirect?last_domain=testserver&redirect_to=/"
                    ),
                    "client_id": settings.AUTH0_CLIENT_ID,
                }
            ),
        )
