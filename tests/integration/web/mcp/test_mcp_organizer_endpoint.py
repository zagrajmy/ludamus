import json
from http import HTTPStatus

import pytest

from ludamus.adapters.db.django.models import Announcement
from ludamus.gates.web.django.mcp.views import mint_organizer_token, mint_token
from tests.integration.conftest import EventFactory, SphereFactory, UserFactory
from tests.integration.utils import assert_response
from tests.integration.web.mcp.test_mcp_endpoint import tool_text

URL = "/mcp/organizer/"


@pytest.fixture(name="manager")
def manager_fixture(sphere):
    user = UserFactory(username="orgmanager")
    sphere.managers.add(user)
    return user


@pytest.fixture(name="org_token")
def org_token_fixture(manager, sphere):
    return mint_organizer_token(user_id=manager.pk, sphere_id=sphere.pk)


def post_org(client, payload, *, token=None):
    extra = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    return client.post(
        URL, data=json.dumps(payload), content_type="application/json", **extra
    )


def call_org_tool(client, token, name, arguments):
    return post_org(
        client,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        token=token,
    )


PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


class TestOrganizerAuthentication:
    def test_get_not_allowed(self, client):
        assert_response(client.get(URL), HTTPStatus.METHOD_NOT_ALLOWED)

    def test_missing_token(self, client):
        response = post_org(client, PING)

        assert_response(response, HTTPStatus.UNAUTHORIZED)
        assert response.json() == {
            "error": "A valid organizer Bearer token is required."
        }

    def test_maintainer_token_is_rejected(self, client):
        superuser = UserFactory(username="root", is_superuser=True)

        response = post_org(client, PING, token=mint_token(superuser.pk))

        assert_response(response, HTTPStatus.UNAUTHORIZED)

    def test_organizer_token_is_rejected_on_maintainer_endpoint(
        self, client, org_token
    ):
        response = client.post(
            "/mcp/",
            data=json.dumps(PING),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {org_token}",
        )

        assert_response(response, HTTPStatus.UNAUTHORIZED)

    def test_non_manager_token(self, client, active_user, sphere):
        token = mint_organizer_token(user_id=active_user.pk, sphere_id=sphere.pk)

        response = post_org(client, PING, token=token)

        assert_response(response, HTTPStatus.UNAUTHORIZED)

    def test_manager_of_another_sphere(self, client, manager):
        other = SphereFactory()
        token = mint_organizer_token(user_id=manager.pk, sphere_id=other.pk)

        response = post_org(client, PING, token=token)

        assert_response(response, HTTPStatus.UNAUTHORIZED)

    def test_deactivated_manager(self, client, manager, org_token):
        manager.is_active = False
        manager.save()

        response = post_org(client, PING, token=org_token)

        assert_response(response, HTTPStatus.UNAUTHORIZED)

    def test_manager_can_ping(self, client, org_token):
        response = post_org(client, PING, token=org_token)

        assert response.json() == {"jsonrpc": "2.0", "id": 1, "result": {}}


class TestOrganizerTools:
    def test_tools_list(self, client, org_token):
        response = post_org(
            client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token=org_token
        )

        tools = response.json()["result"]["tools"]
        assert [tool["name"] for tool in tools] == [
            "get_sphere",
            "list_events",
            "list_announcements",
            "create_announcement",
            "update_announcement",
            "delete_announcement",
        ]
        assert all(
            "sphere_id" not in tool["inputSchema"].get("properties", {})
            for tool in tools
        )

    def test_get_sphere_uses_token_sphere(self, client, org_token, sphere):
        response = call_org_tool(client, org_token, "get_sphere", {})

        assert json.loads(tool_text(response))["pk"] == sphere.pk

    def test_list_events_scoped_to_token_sphere(self, client, org_token, sphere):
        own = EventFactory(sphere=sphere)
        EventFactory(sphere=SphereFactory())

        response = call_org_tool(client, org_token, "list_events", {})

        events = json.loads(tool_text(response))
        assert [item["slug"] for item in events] == [own.slug]

    def test_announcement_crud_scoped_to_token_sphere(self, client, org_token, sphere):
        create = call_org_tool(
            client,
            org_token,
            "create_announcement",
            {"title": "Zbiórka wolontariuszy", "content": "Sala 101, sobota 9:00."},
        )
        created = json.loads(tool_text(create))
        announcement = Announcement.objects.get(pk=created["pk"])
        assert announcement.sphere_id == sphere.pk
        assert announcement.is_published is False

        update = call_org_tool(
            client,
            org_token,
            "update_announcement",
            {
                "announcement_id": created["pk"],
                "title": "Zbiórka wolontariuszy",
                "content": "Sala 102, sobota 9:00.",
                "is_published": True,
            },
        )
        assert json.loads(tool_text(update))["is_published"] is True

        delete = call_org_tool(
            client, org_token, "delete_announcement", {"announcement_id": created["pk"]}
        )
        assert json.loads(tool_text(delete)) == {"deleted": created["pk"]}
        assert not Announcement.objects.filter(pk=created["pk"]).exists()

    def test_maintainer_tools_are_unreachable(self, client, org_token):
        response = call_org_tool(client, org_token, "list_spheres", {})

        assert response.json()["error"] == {
            "code": -32602,
            "message": "Unknown tool: list_spheres",
        }
