import json
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from tests.integration.utils import assert_response

URL = reverse("multiverse:panel:mcp-token")
PERMISSION_ERROR = "You don't have permission to access the sphere panel."

TAB_URLS = {
    "general": "/multiverse/panel/",
    "connections": "/multiverse/panel/connections/",
    "announcements": "/multiverse/panel/announcements/",
    "mcp": "/multiverse/panel/mcp/",
}
MCP_PANEL_CONTEXT = {
    "events": [],
    "current_event": None,
    "is_proposal_active": False,
    "active_nav": "sphere-settings",
    "active_tab": "mcp",
    "tab_urls": TAB_URLS,
    "endpoint_url": "http://testserver/mcp/organizer/",
    "token_max_age_days": 30,
}


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
