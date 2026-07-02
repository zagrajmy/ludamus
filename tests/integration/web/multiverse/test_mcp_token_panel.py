import json
from http import HTTPStatus
from unittest.mock import ANY

from django.contrib import messages
from django.urls import reverse

from tests.integration.utils import assert_response

URL = reverse("multiverse:panel:mcp-token")
PERMISSION_ERROR = "You don't have permission to access the sphere panel."


class TestMcpTokenPanelPageView:
    def test_get_redirects_anonymous_user_to_login(self, client):
        response = client.get(URL)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={URL}"
        )

    def test_get_redirects_non_manager_user(self, authenticated_client):
        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:index"),
            messages=((messages.ERROR, PERMISSION_ERROR),),
        )

    def test_get_shows_generate_button(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/mcp-token.html",
            context_data=ANY,
            contains="Generate token",
            not_contains="claude mcp add",
        )
        assert response.context_data["token"] is None
        assert response.context_data["is_mcp_tab"] is True

    def test_post_mints_working_organizer_token(
        self, authenticated_client, active_user, sphere, client
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/mcp-token.html",
            context_data=ANY,
            contains=["claude mcp add", "http://testserver/mcp/organizer/"],
        )
        token = response.context_data["token"]
        assert token

        ping = client.post(
            "/mcp/organizer/",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert ping.json() == {"jsonrpc": "2.0", "id": 1, "result": {}}
