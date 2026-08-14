from http import HTTPStatus

from django.core import signing
from django.urls import reverse

from ludamus.gates.web.django.mcp.tokens import SIGNING_SALT
from ludamus.gates.web.django.panel import settings_tab_urls
from ludamus.pacts.mcp import ToolScope
from tests.integration.conftest import EventFactory, SphereFactory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
)


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


class TestEventMcpTokenAccess:
    def test_redirects_anonymous_user_to_login(self, client, event):
        url = _url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_rejects_authenticated_non_manager(self, authenticated_client, event):
        response = authenticated_client.get(_url(event))

        assert_not_a_manager(response)

    def test_rejects_event_from_another_sphere(self, panel_client):
        foreign = EventFactory(sphere=SphereFactory(), slug="foreign-event")

        response = panel_client.get(_url(foreign))

        assert_event_not_found(response)

    def test_manager_mints_exact_event_scoped_token(
        self, panel_client, event, active_user
    ):
        response = panel_client.post(_url(event))

        token = response.context["token"]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/mcp-token.html",
            context_data=_expected_context(event, token=token),
            cache_control={
                "max-age=0",
                "no-cache",
                "no-store",
                "must-revalidate",
                "private",
            },
        )
        payload = signing.loads(token, salt=SIGNING_SALT)
        assert payload == {
            "user_id": active_user.pk,
            "scope": ToolScope.ORGANIZER.value,
            "sphere_id": event.sphere_id,
            "event_id": event.pk,
        }

    def test_superuser_can_mint_without_sphere_membership(
        self, authenticated_client, active_user, event
    ):
        active_user.is_superuser = True
        active_user.save()

        response = authenticated_client.post(_url(event))

        token = response.context["token"]
        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/mcp-token.html",
            context_data=_expected_context(event, token=token),
            cache_control={
                "max-age=0",
                "no-cache",
                "no-store",
                "must-revalidate",
                "private",
            },
        )
        payload = signing.loads(token, salt=SIGNING_SALT)
        assert payload == {
            "user_id": active_user.pk,
            "scope": ToolScope.ORGANIZER.value,
            "sphere_id": event.sphere_id,
            "event_id": event.pk,
        }
