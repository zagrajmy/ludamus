import json
import logging
from http import HTTPStatus

import pytest
from django.core import signing
from freezegun import freeze_time

from ludamus.adapters.db.django.models import Announcement
from ludamus.gates.mcp.protocol import PARSE_ERROR
from ludamus.gates.web.django.mcp.views import SIGNING_SALT, mint_token
from tests.integration.conftest import EventFactory, UserFactory
from tests.integration.utils import assert_response

URL = "/mcp/"


@pytest.fixture(name="superuser")
def superuser_fixture():
    return UserFactory(username="maintainer", is_superuser=True)


@pytest.fixture(name="token")
def token_fixture(superuser):
    return mint_token(superuser.pk)


def post_message(client, payload, *, token=None):
    extra = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
    return client.post(
        URL, data=json.dumps(payload), content_type="application/json", **extra
    )


def call_tool(client, token, name, arguments):
    return post_message(
        client,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        token=token,
    )


def tool_text(response):
    result = response.json()["result"]
    assert result["isError"] is False, result
    return result["content"][0]["text"]


class TestAuthentication:
    def test_get_not_allowed(self, client):
        response = client.get(URL)

        assert_response(response, HTTPStatus.METHOD_NOT_ALLOWED)

    def test_missing_token(self, client):
        response = post_message(client, {"jsonrpc": "2.0", "id": 1, "method": "ping"})

        assert_response(response, HTTPStatus.UNAUTHORIZED)
        assert response["WWW-Authenticate"] == "Bearer"
        assert response.json() == {
            "error": "A valid maintainer Bearer token is required."
        }

    def test_garbage_token(self, client):
        response = post_message(
            client,
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            token="not-a-real-token",
        )

        assert_response(response, HTTPStatus.UNAUTHORIZED)

    def test_non_superuser_token(self, client, active_user):
        response = post_message(
            client,
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            token=mint_token(active_user.pk),
        )

        assert_response(response, HTTPStatus.UNAUTHORIZED)

    def test_deactivated_superuser_token(self, client, superuser, token):
        superuser.is_active = False
        superuser.save()

        response = post_message(
            client, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=token
        )

        assert_response(response, HTTPStatus.UNAUTHORIZED)

    def test_expired_token(self, client, superuser):
        with freeze_time("2020-01-01"):
            token = mint_token(superuser.pk)

        response = post_message(
            client, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=token
        )

        assert_response(response, HTTPStatus.UNAUTHORIZED)

    def test_signed_non_dict_token(self, client):
        token = signing.dumps("not-a-payload-dict", salt=SIGNING_SALT)

        response = post_message(
            client, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=token
        )

        assert_response(response, HTTPStatus.UNAUTHORIZED)

    def test_signed_non_int_user_id_token(self, client):
        token = signing.dumps({"user_id": "42"}, salt=SIGNING_SALT)

        response = post_message(
            client, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=token
        )

        assert_response(response, HTTPStatus.UNAUTHORIZED)


class TestProtocol:
    def test_initialize(self, client, token):
        response = post_message(
            client,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
            token=token,
        )

        assert_response(response, HTTPStatus.OK)
        assert response.json() == {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "ludamus",
                    "title": "Zagrajmy",
                    "version": "0.1.0",
                },
            },
        }

    def test_initialize_unknown_version_falls_back(self, client, token):
        response = post_message(
            client,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "1999-01-01"},
            },
            token=token,
        )

        assert response.json()["result"]["protocolVersion"] == "2025-06-18"

    def test_initialized_notification_is_accepted(self, client, token):
        response = post_message(
            client,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            token=token,
        )

        assert_response(response, HTTPStatus.ACCEPTED)
        assert response.content == b""

    def test_ping(self, client, token):
        response = post_message(
            client, {"jsonrpc": "2.0", "id": 7, "method": "ping"}, token=token
        )

        assert response.json() == {"jsonrpc": "2.0", "id": 7, "result": {}}

    def test_tools_list(self, client, token):
        response = post_message(
            client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token=token
        )

        tools = response.json()["result"]["tools"]
        assert [tool["name"] for tool in tools] == [
            "list_spheres",
            "get_sphere",
            "list_events",
            "get_event",
            "list_announcements",
            "create_announcement",
            "update_announcement",
            "delete_announcement",
        ]
        schema = tools[1]["inputSchema"]
        assert schema["required"] == ["sphere_id"]
        assert schema["properties"]["sphere_id"]["type"] == "integer"

    def test_unknown_method(self, client, token):
        response = post_message(
            client, {"jsonrpc": "2.0", "id": 1, "method": "resources/list"}, token=token
        )

        assert response.json()["error"] == {
            "code": -32601,
            "message": "Method not found: resources/list",
        }

    def test_missing_method(self, client, token):
        response = post_message(client, {"jsonrpc": "2.0", "id": 1}, token=token)

        assert response.json()["error"] == {
            "code": -32600,
            "message": "Invalid request",
        }

    def test_invalid_json(self, client, token):
        response = client.post(
            URL,
            data="{not json",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        assert_response(response, HTTPStatus.BAD_REQUEST)
        assert response.json()["error"]["code"] == PARSE_ERROR

    def test_non_object_message(self, client, token):
        response = post_message(client, [1, 2, 3], token=token)

        assert_response(response, HTTPStatus.BAD_REQUEST)
        assert response.json()["error"]["code"] == PARSE_ERROR


class TestTools:
    def test_missing_tool_name(self, client, token):
        response = post_message(
            client,
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}},
            token=token,
        )

        assert response.json()["error"] == {
            "code": -32602,
            "message": "Invalid tool call params",
        }

    def test_non_dict_arguments(self, client, token):
        response = post_message(
            client,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "list_spheres", "arguments": "nope"},
            },
            token=token,
        )

        assert response.json()["error"] == {
            "code": -32602,
            "message": "Invalid tool call params",
        }

    def test_unknown_tool(self, client, token):
        response = call_tool(client, token, "drop_database", {})

        assert response.json()["error"] == {
            "code": -32602,
            "message": "Unknown tool: drop_database",
        }

    def test_falsy_non_dict_arguments_are_invalid(self, client, token):
        response = post_message(
            client,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "list_spheres", "arguments": []},
            },
            token=token,
        )

        assert response.json()["error"] == {
            "code": -32602,
            "message": "Invalid tool call params",
        }

    def test_invalid_arguments(self, client, token):
        response = call_tool(client, token, "get_sphere", {})

        result = response.json()["result"]
        assert result["isError"] is True
        assert "Invalid arguments" in result["content"][0]["text"]

    def test_list_spheres(self, client, token, sphere):
        response = call_tool(client, token, "list_spheres", {})

        assert json.loads(tool_text(response)) == [
            {"pk": sphere.pk, "name": sphere.name, "domain": "testserver"}
        ]

    def test_get_sphere(self, client, token, sphere):
        response = call_tool(client, token, "get_sphere", {"sphere_id": sphere.pk})

        assert json.loads(tool_text(response))["pk"] == sphere.pk

    def test_list_events(self, client, token, sphere):
        event = EventFactory(sphere=sphere, name="Konwent Testowy")

        response = call_tool(client, token, "list_events", {"sphere_id": sphere.pk})

        events = json.loads(tool_text(response))
        assert [item["slug"] for item in events] == [event.slug]

    def test_get_event(self, client, token, sphere):
        event = EventFactory(sphere=sphere)

        response = call_tool(
            client, token, "get_event", {"sphere_id": sphere.pk, "slug": event.slug}
        )

        assert json.loads(tool_text(response))["pk"] == event.pk

    def test_get_event_not_found(self, client, token, sphere):
        response = call_tool(
            client, token, "get_event", {"sphere_id": sphere.pk, "slug": "nope"}
        )

        result = response.json()["result"]
        assert result["isError"] is True
        assert result["content"][0]["text"] == "Resource not found"

    def test_announcement_crud(self, client, token, sphere):
        create = call_tool(
            client,
            token,
            "create_announcement",
            {
                "sphere_id": sphere.pk,
                "title": "Serwis w nocy",
                "content": "Zagrajmy będzie niedostępne od 2:00 do 3:00.",
            },
        )
        created = json.loads(tool_text(create))
        assert created["title"] == "Serwis w nocy"
        assert created["is_published"] is False

        update = call_tool(
            client,
            token,
            "update_announcement",
            {
                "sphere_id": sphere.pk,
                "announcement_id": created["pk"],
                "title": "Serwis w nocy",
                "content": "Przerwa przełożona na jutro.",
                "is_published": True,
            },
        )
        assert json.loads(tool_text(update))["is_published"] is True
        announcement = Announcement.objects.get(pk=created["pk"])
        assert announcement.content == "Przerwa przełożona na jutro."

        delete = call_tool(
            client,
            token,
            "delete_announcement",
            {"sphere_id": sphere.pk, "announcement_id": created["pk"]},
        )
        assert json.loads(tool_text(delete)) == {"deleted": created["pk"]}
        assert not Announcement.objects.filter(pk=created["pk"]).exists()

    def test_list_announcements_empty(self, client, token, sphere):
        response = call_tool(
            client, token, "list_announcements", {"sphere_id": sphere.pk}
        )

        assert json.loads(tool_text(response)) == []


AUDIT_LOGGER = "ludamus.gates.mcp.protocol"


def audit_records(caplog):
    return [record for record in caplog.records if record.name == AUDIT_LOGGER]


class TestAudit:
    def test_successful_call_is_logged(self, client, token, superuser, sphere, caplog):
        caplog.set_level(logging.INFO, logger=AUDIT_LOGGER)

        call_tool(client, token, "get_sphere", {"sphere_id": sphere.pk})

        records = audit_records(caplog)
        assert len(records) == 1
        assert records[0].args == (
            superuser.pk,
            "maintainer",
            None,
            "get_sphere",
            "ok",
            {"sphere_id": sphere.pk},
        )
        assert records[0].getMessage() == (
            f"mcp.tools_call user_id={superuser.pk} scope=maintainer "
            f"sphere_id=None tool='get_sphere' outcome=ok "
            f"arguments={{'sphere_id': {sphere.pk}}}"
        )

    def test_unknown_tool_is_logged(self, client, token, superuser, caplog):
        caplog.set_level(logging.INFO, logger=AUDIT_LOGGER)

        call_tool(client, token, "drop_database", {"force": True})

        records = audit_records(caplog)
        assert len(records) == 1
        assert records[0].args == (
            superuser.pk,
            "maintainer",
            None,
            "drop_database",
            "unknown-tool",
            {"force": True},
        )

    def test_invalid_arguments_are_logged_as_error(
        self, client, token, superuser, caplog
    ):
        caplog.set_level(logging.INFO, logger=AUDIT_LOGGER)

        call_tool(client, token, "get_sphere", {})

        records = audit_records(caplog)
        assert len(records) == 1
        assert records[0].args == (
            superuser.pk,
            "maintainer",
            None,
            "get_sphere",
            "error",
            {},
        )

    def test_other_methods_are_not_logged(self, client, token, caplog):
        caplog.set_level(logging.INFO, logger=AUDIT_LOGGER)

        post_message(client, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=token)

        assert audit_records(caplog) == []
