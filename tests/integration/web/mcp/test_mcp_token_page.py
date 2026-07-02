from http import HTTPStatus
from unittest.mock import ANY

import pytest

from tests.integration.conftest import UserFactory
from tests.integration.utils import assert_response, assert_response_404
from tests.integration.web.mcp.test_mcp_endpoint import post_message

URL = "/mcp/token/"


@pytest.fixture(name="superuser_client")
def superuser_client_fixture(client):
    superuser = UserFactory(username="maintainer", is_superuser=True)
    client.force_login(superuser)
    return client


class TestMcpTokenPageView:
    def test_login_required(self, client):
        response = client.get(URL)

        assert_response(
            response, HTTPStatus.FOUND, url="/crowd/login-required/?next=/mcp/token/"
        )

    def test_non_superuser_gets_404(self, authenticated_client):
        assert_response_404(authenticated_client.get(URL))
        assert_response_404(authenticated_client.post(URL))

    def test_get_shows_generate_button(self, superuser_client):
        response = superuser_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="mcp/token.html",
            context_data={
                "token": None,
                "endpoint_url": "http://testserver/mcp/",
                "token_max_age_days": 30,
            },
            contains="Generate token",
            not_contains="claude mcp add",
        )

    def test_post_mints_working_token(self, superuser_client, client):
        response = superuser_client.post(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="mcp/token.html",
            context_data={
                "token": ANY,
                "endpoint_url": "http://testserver/mcp/",
                "token_max_age_days": 30,
            },
            contains=["claude mcp add", "http://testserver/mcp/"],
        )
        token = response.context_data["token"]
        assert token

        ping = post_message(
            client, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=token
        )
        assert ping.json() == {"jsonrpc": "2.0", "id": 1, "result": {}}
