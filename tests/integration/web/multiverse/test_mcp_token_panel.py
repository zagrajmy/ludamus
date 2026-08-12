import json
from http import HTTPStatus

from django.urls import reverse

from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.multiverse.helpers import (
    assert_not_a_sphere_manager,
    sphere_settings_context,
)

URL = reverse("multiverse:panel:mcp-token")
MCP_PANEL_CONTEXT = sphere_settings_context(active_tab="mcp") | {
    "endpoint_url": "http://testserver/mcp/organizer/",
    "token_max_age_days": 30,
}


class TestMcpTokenPanelPageView:
    def test_get_redirects_anonymous_user_to_login(self, client):
        response = client.get(URL)

        assert_login_required(response, URL)

    def test_get_redirects_non_manager_user(self, authenticated_client):
        response = authenticated_client.get(URL)

        assert_not_a_sphere_manager(response)

    def test_get_shows_generate_button(self, authenticated_client, active_user, sphere):
        sphere.managers.add(active_user)

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/mcp-token.html",
            context_data=MCP_PANEL_CONTEXT | {"token": None},
            contains="Generate token",
            not_contains="claude mcp add",
        )

    def test_post_mints_working_organizer_token(
        self, authenticated_client, active_user, sphere, client
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(URL)

        token = response.context_data.pop("token")
        assert token
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/mcp-token.html",
            context_data=MCP_PANEL_CONTEXT,
            contains=["claude mcp add", "http://testserver/mcp/organizer/"],
        )

        ping = client.post(
            "/mcp/organizer/",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert ping.json() == {"jsonrpc": "2.0", "id": 1, "result": {}}

    def test_post_mints_working_token_for_non_manager_superuser(
        self, authenticated_client, active_user, client
    ):
        active_user.is_superuser = True
        active_user.save()

        response = authenticated_client.post(URL)

        token = response.context_data.pop("token")
        assert token
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="multiverse/panel/mcp-token.html",
            context_data=MCP_PANEL_CONTEXT,
            contains=["claude mcp add", "http://testserver/mcp/organizer/"],
        )

        ping = client.post(
            "/mcp/organizer/",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert ping.json() == {"jsonrpc": "2.0", "id": 1, "result": {}}
