from http import HTTPStatus

from django.urls import reverse

from ludamus.gates.web.django.panel import settings_tab_urls
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
)

TEMPLATE = "panel/mcp-token.html"


def _url(event):
    return reverse("panel:event-mcp-token", kwargs={"slug": event.slug})


def _expected_context(event, *, token):
    return {
        **panel_context(event, active_nav="settings"),
        "active_tab": "mcp",
        "tab_urls": settings_tab_urls(event.slug),
        "token": token,
        "endpoint_url": "http://testserver/mcp/organizer/",
        "token_max_age_days": 30,
    }


class TestEventMcpTokenPageView:
    def test_get_redirects_anonymous_user_to_login(self, client, event):
        url = _url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_get_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.get(_url(event))

        assert_not_a_manager(response)

    def test_get_shows_generate_form(self, panel_client, event):
        response = panel_client.get(_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=TEMPLATE,
            context_data=_expected_context(event, token=None),
        )

    def test_redirects_on_invalid_slug(self, panel_client):
        url = reverse("panel:event-mcp-token", kwargs={"slug": "bad-slug"})

        response = panel_client.get(url)

        assert_event_not_found(response)

    def test_post_mints_working_organizer_token(self, panel_client, event, client):
        response = panel_client.post(_url(event))

        token = response.context["token"]
        assert token
        assert_response(
            response,
            HTTPStatus.OK,
            template_name=TEMPLATE,
            context_data=_expected_context(event, token=token),
        )

        ping = client.post(
            "/mcp/organizer/",
            data='{"jsonrpc": "2.0", "id": 1, "method": "ping"}',
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert ping.json() == {"jsonrpc": "2.0", "id": 1, "result": {}}

    def test_post_mints_working_token_for_non_manager_superuser(
        self, authenticated_client, active_user, event, client
    ):
        active_user.is_superuser = True
        active_user.save()

        response = authenticated_client.post(_url(event))

        token = response.context["token"]
        assert token
        assert_response(
            response,
            HTTPStatus.OK,
            template_name=TEMPLATE,
            context_data=_expected_context(event, token=token),
        )

        ping = client.post(
            "/mcp/organizer/",
            data='{"jsonrpc": "2.0", "id": 1, "method": "ping"}',
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert ping.json() == {"jsonrpc": "2.0", "id": 1, "result": {}}
