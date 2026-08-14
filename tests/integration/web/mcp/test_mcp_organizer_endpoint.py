import json
from datetime import timedelta
from http import HTTPStatus

import pytest
from django.core import signing

from ludamus.gates.web.django.mcp.tokens import (
    SIGNING_SALT,
    mint_organizer_token,
    mint_token,
)
from ludamus.links.db.django.models import (
    AgendaItem,
    Announcement,
    ScheduleChangeLog,
    Space,
    Track,
)
from ludamus.pacts.mcp import ToolScope
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    SessionFactory,
    SpaceFactory,
    SphereFactory,
    TimeSlotFactory,
    UserFactory,
)
from tests.integration.utils import assert_response
from tests.integration.web.mcp.test_mcp_endpoint import tool_text

URL = "/mcp/organizer/"
WRITE_TOOLS = {
    "create_space",
    "create_time_slot",
    "create_track",
    "create_proposal_category",
    "find_or_create_facilitator",
    "create_session",
    "create_sessions",
    "assign_session",
    "assign_sessions",
}


@pytest.fixture(name="manager")
def manager_fixture(sphere):
    user = UserFactory(username="orgmanager")
    sphere.managers.add(user)
    return user


@pytest.fixture(name="org_token")
def org_token_fixture(manager, sphere, event):
    return mint_organizer_token(
        user_id=manager.pk, sphere_id=sphere.pk, event_id=event.pk
    )


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

    def test_non_manager_token(self, client, active_user, sphere, event):
        token = mint_organizer_token(
            user_id=active_user.pk, sphere_id=sphere.pk, event_id=event.pk
        )

        response = post_org(client, PING, token=token)

        assert_response(response, HTTPStatus.UNAUTHORIZED)

    def test_manager_of_another_sphere(self, client, manager):
        other = SphereFactory()
        other_event = EventFactory(sphere=other)
        token = mint_organizer_token(
            user_id=manager.pk, sphere_id=other.pk, event_id=other_event.pk
        )

        response = post_org(client, PING, token=token)

        assert_response(response, HTTPStatus.UNAUTHORIZED)

    def test_token_without_event_id(self, client, manager, sphere):
        token = signing.dumps(
            {
                "user_id": manager.pk,
                "scope": ToolScope.ORGANIZER.value,
                "sphere_id": sphere.pk,
            },
            salt=SIGNING_SALT,
        )

        response = post_org(client, PING, token=token)

        assert_response(response, HTTPStatus.UNAUTHORIZED)

    def test_token_for_event_outside_sphere(self, client, manager, sphere):
        foreign = EventFactory(sphere=SphereFactory())
        token = mint_organizer_token(
            user_id=manager.pk, sphere_id=sphere.pk, event_id=foreign.pk
        )

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

    def test_non_manager_superuser_can_ping(self, client, sphere, event):
        superuser = UserFactory(username="orgroot", is_superuser=True)
        token = mint_organizer_token(
            user_id=superuser.pk, sphere_id=sphere.pk, event_id=event.pk
        )

        response = post_org(client, PING, token=token)

        assert response.json() == {"jsonrpc": "2.0", "id": 1, "result": {}}

    def test_deactivated_superuser(self, client, sphere, event):
        superuser = UserFactory(username="orgroot", is_superuser=True, is_active=False)
        token = mint_organizer_token(
            user_id=superuser.pk, sphere_id=sphere.pk, event_id=event.pk
        )

        response = post_org(client, PING, token=token)

        assert_response(response, HTTPStatus.UNAUTHORIZED)


class TestOrganizerTools:
    def test_tools_list(self, client, org_token):
        response = post_org(
            client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token=org_token
        )

        tools = response.json()["result"]["tools"]
        tool_names = {tool["name"] for tool in tools}
        assert tool_names >= WRITE_TOOLS
        assert "create_event" not in tool_names
        assert all(
            "sphere_id" not in tool["inputSchema"].get("properties", {})
            for tool in tools
        )
        assert all(
            "event_id" not in tool["inputSchema"].get("properties", {})
            for tool in tools
            if tool["name"] in WRITE_TOOLS
        )

    def test_get_sphere_uses_token_sphere(self, client, org_token, sphere):
        response = call_org_tool(client, org_token, "get_sphere", {})

        assert json.loads(tool_text(response))["pk"] == sphere.pk

    def test_list_events_scoped_to_token_sphere(self, client, org_token, sphere, event):
        EventFactory(sphere=SphereFactory())

        response = call_org_tool(client, org_token, "list_events", {})

        events = json.loads(tool_text(response))
        assert [item["slug"] for item in events] == [event.slug]

    def test_list_announcements_scoped_to_token_sphere(self, client, org_token, sphere):
        Announcement.objects.create(
            sphere=sphere, title="Zbiórka", content="Sala 101", is_published=True
        )
        Announcement.objects.create(
            sphere=SphereFactory(), title="Inna sfera", content="", is_published=True
        )

        listed = json.loads(
            tool_text(call_org_tool(client, org_token, "list_announcements", {}))
        )
        assert [item["title"] for item in listed] == ["Zbiórka"]

    def test_get_event_by_slug_in_sphere(self, client, org_token, event):
        response = call_org_tool(client, org_token, "get_event", {"slug": event.slug})

        assert json.loads(tool_text(response))["pk"] == event.pk

    def test_list_spaces_reads_sibling_event_in_sphere(self, client, org_token, sphere):
        sibling = EventFactory(sphere=sphere)

        response = call_org_tool(
            client, org_token, "list_spaces", {"event_id": sibling.pk}
        )

        assert json.loads(tool_text(response)) == []

    def test_create_space_writes_token_event_only(
        self, client, org_token, sphere, event
    ):
        sibling = EventFactory(sphere=sphere)

        created = json.loads(
            tool_text(
                call_org_tool(client, org_token, "create_space", {"name": "Aula A"})
            )
        )

        assert created["event_id"] == event.pk
        assert created["event_id"] != sibling.pk
        assert Space.objects.filter(event=event, name="Aula A").exists()
        assert not Space.objects.filter(event=sibling).exists()

    def test_programme_tools_reject_foreign_event(self, client, org_token):
        foreign = EventFactory(sphere=SphereFactory())

        response = call_org_tool(
            client, org_token, "list_spaces", {"event_id": foreign.pk}
        )

        result = response.json()["result"]
        assert result["isError"] is True
        assert result["content"][0]["text"] == "Resource not found"

    def test_create_event_is_unreachable(self, client, org_token):
        response = call_org_tool(
            client,
            org_token,
            "create_event",
            {
                "name": "Bachanalia Fantastyczne 2026",
                "slug": "bachanalia-2026",
                "start_time": "2026-09-25T10:00:00+02:00",
                "end_time": "2026-09-27T18:00:00+02:00",
            },
        )

        assert_response(response, HTTPStatus.OK)
        error = response.json()["error"]
        assert error == {"code": -32602, "message": "Unknown tool: create_event"}

    def test_maintainer_tools_are_unreachable(self, client, org_token):
        response = call_org_tool(client, org_token, "list_spheres", {})

        assert_response(response, HTTPStatus.OK)
        error = response.json()["error"]
        assert error == {"code": -32602, "message": "Unknown tool: list_spheres"}


class TestOrganizerProgrammeValidation:
    def test_create_session_rejects_blank_source_row_id(self, client, org_token):
        response = call_org_tool(
            client,
            org_token,
            "create_session",
            {"source_row_id": "   ", "title": "Bad key", "category_id": 1},
        )

        result = response.json()["result"]
        assert result["isError"] is True
        assert "source_row_id must be non-empty" in result["content"][0]["text"]

    def test_assign_session_rejects_inverted_time_range(self, client, org_token, event):
        session = SessionFactory(event=event, category=None, status="accepted")
        space = SpaceFactory(event=event, parent=None)

        response = call_org_tool(
            client,
            org_token,
            "assign_session",
            {
                "session_id": session.pk,
                "space_id": space.pk,
                "start_time": (event.start_time + timedelta(hours=2)).isoformat(),
                "end_time": (event.start_time + timedelta(hours=1)).isoformat(),
            },
        )

        result = response.json()["result"]
        assert result["isError"] is True
        assert result["content"][0]["text"] == "end_time must be after start_time"
        assert not AgendaItem.objects.filter(session=session).exists()


class TestOrganizerProgrammeTools:
    def test_programme_seed_happy_path(self, client, org_token, event):
        slot_start = event.start_time + timedelta(hours=2)
        slot_end = slot_start + timedelta(hours=2)
        assign_start = slot_start + timedelta(minutes=30)
        assign_end = assign_start + timedelta(hours=1)

        category = json.loads(
            tool_text(
                call_org_tool(
                    client, org_token, "create_proposal_category", {"name": "Warsztaty"}
                )
            )
        )
        categories = json.loads(
            tool_text(
                call_org_tool(
                    client,
                    org_token,
                    "list_proposal_categories",
                    {"event_id": event.pk},
                )
            )
        )
        assert [item["pk"] for item in categories] == [category["pk"]]

        json.loads(
            tool_text(
                call_org_tool(
                    client,
                    org_token,
                    "create_time_slot",
                    {
                        "start_time": slot_start.isoformat(),
                        "end_time": slot_end.isoformat(),
                    },
                )
            )
        )
        venue = json.loads(
            tool_text(
                call_org_tool(client, org_token, "create_space", {"name": "Venue"})
            )
        )
        room = json.loads(
            tool_text(
                call_org_tool(
                    client,
                    org_token,
                    "create_space",
                    {"name": "Aula A", "parent_id": venue["pk"]},
                )
            )
        )
        track = json.loads(
            tool_text(
                call_org_tool(client, org_token, "create_track", {"name": "Main"})
            )
        )
        facilitator = json.loads(
            tool_text(
                call_org_tool(
                    client,
                    org_token,
                    "find_or_create_facilitator",
                    {"display_name": "Jan Kowalski"},
                )
            )
        )
        found = json.loads(
            tool_text(
                call_org_tool(
                    client,
                    org_token,
                    "find_or_create_facilitator",
                    {"display_name": "Jan Kowalski"},
                )
            )
        )
        assert found["pk"] == facilitator["pk"]

        session = json.loads(
            tool_text(
                call_org_tool(
                    client,
                    org_token,
                    "create_session",
                    {
                        "source_row_id": "bf25-row-1",
                        "title": "Wprowadzenie",
                        "category_id": category["pk"],
                        "facilitator_ids": [facilitator["pk"]],
                        "track_ids": [track["pk"]],
                    },
                )
            )
        )
        retry = json.loads(
            tool_text(
                call_org_tool(
                    client,
                    org_token,
                    "create_session",
                    {
                        "source_row_id": "bf25-row-1",
                        "title": "Wprowadzenie",
                        "category_id": category["pk"],
                    },
                )
            )
        )
        assert retry["pk"] == session["pk"]

        assigned = json.loads(
            tool_text(
                call_org_tool(
                    client,
                    org_token,
                    "assign_session",
                    {
                        "session_id": session["pk"],
                        "space_id": room["pk"],
                        "start_time": assign_start.isoformat(),
                        "end_time": assign_end.isoformat(),
                    },
                )
            )
        )
        assert assigned == {"session_id": session["pk"], "space_id": room["pk"]}

        assert json.loads(
            tool_text(
                call_org_tool(client, org_token, "list_spaces", {"event_id": event.pk})
            )
        ) == [
            {
                "pk": room["pk"],
                "name": "Aula A",
                "path": "Venue > Aula A",
                "capacity": None,
                "parent_id": venue["pk"],
            }
        ]
        assert (
            len(
                json.loads(
                    tool_text(
                        call_org_tool(
                            client, org_token, "list_time_slots", {"event_id": event.pk}
                        )
                    )
                )
            )
            == 1
        )
        assert (
            json.loads(
                tool_text(
                    call_org_tool(
                        client, org_token, "list_tracks", {"event_id": event.pk}
                    )
                )
            )[0]["pk"]
            == track["pk"]
        )
        assert (
            json.loads(
                tool_text(
                    call_org_tool(
                        client, org_token, "list_sessions", {"event_id": event.pk}
                    )
                )
            )[0]["pk"]
            == session["pk"]
        )
        assert (
            json.loads(
                tool_text(
                    call_org_tool(
                        client, org_token, "list_facilitators", {"event_id": event.pk}
                    )
                )
            )[0]["pk"]
            == facilitator["pk"]
        )

    def test_batch_creates_and_assigns_sessions_idempotently(
        self, client, org_token, event
    ):
        category = json.loads(
            tool_text(
                call_org_tool(
                    client,
                    org_token,
                    "create_proposal_category",
                    {"name": "Batch category"},
                )
            )
        )
        venue = SpaceFactory(event=event, parent=None, name="Batch venue")
        room = SpaceFactory(event=event, parent=venue, name="Batch room")
        TimeSlotFactory(
            event=event,
            start_time=event.start_time,
            end_time=event.start_time + timedelta(hours=4),
        )
        sessions = [
            {
                "source_row_id": "batch-row-1",
                "title": "Batch one",
                "category_id": category["pk"],
            },
            {
                "source_row_id": "batch-row-2",
                "title": "Batch two",
                "category_id": category["pk"],
            },
        ]

        created = json.loads(
            tool_text(
                call_org_tool(
                    client, org_token, "create_sessions", {"sessions": sessions}
                )
            )
        )
        retried = json.loads(
            tool_text(
                call_org_tool(
                    client, org_token, "create_sessions", {"sessions": sessions}
                )
            )
        )

        assert created["summary"] == {"total": 2, "succeeded": 2, "failed": 0}
        session_ids = [item["session"]["pk"] for item in created["results"]]
        assert [item["session"]["pk"] for item in retried["results"]] == session_ids

        assignments = [
            {
                "session_id": session_ids[0],
                "space_id": room.pk,
                "start_time": (event.start_time + timedelta(hours=1)).isoformat(),
                "end_time": (event.start_time + timedelta(hours=2)).isoformat(),
            },
            {
                "session_id": session_ids[1],
                "space_id": room.pk,
                "start_time": (event.start_time + timedelta(hours=2)).isoformat(),
                "end_time": (event.start_time + timedelta(hours=3)).isoformat(),
            },
        ]

        assigned = json.loads(
            tool_text(
                call_org_tool(
                    client, org_token, "assign_sessions", {"assignments": assignments}
                )
            )
        )
        call_org_tool(
            client, org_token, "assign_sessions", {"assignments": assignments}
        )

        assert assigned["summary"] == {"total": 2, "succeeded": 2, "failed": 0}
        assert AgendaItem.objects.filter(session_id__in=session_ids).count() == len(
            session_ids
        )
        assert ScheduleChangeLog.objects.filter(
            session_id__in=session_ids
        ).count() == len(session_ids)

    def test_batch_session_failure_reports_each_item_and_keeps_successes(
        self, client, org_token, event
    ):
        category = json.loads(
            tool_text(
                call_org_tool(
                    client,
                    org_token,
                    "create_proposal_category",
                    {"name": "Mixed batch"},
                )
            )
        )

        response = call_org_tool(
            client,
            org_token,
            "create_sessions",
            {
                "sessions": [
                    {
                        "source_row_id": "mixed-ok",
                        "title": "Created row",
                        "category_id": category["pk"],
                    },
                    {
                        "source_row_id": "mixed-bad",
                        "title": "Rejected row",
                        "category_id": 999_999,
                    },
                ]
            },
        )

        result = response.json()["result"]
        batch = json.loads(result["content"][0]["text"])
        assert result["isError"] is True
        assert batch["summary"] == {"total": 2, "succeeded": 1, "failed": 1}
        assert [item["status"] for item in batch["results"]] == ["ok", "failed"]
        sessions = json.loads(
            tool_text(
                call_org_tool(
                    client, org_token, "list_sessions", {"event_id": event.pk}
                )
            )
        )
        assert [session["title"] for session in sessions] == ["Created row"]

    @pytest.mark.parametrize(
        "arguments", ({"name": "   "}, {"name": "Invalid capacity", "capacity": -1})
    )
    def test_create_space_reports_invalid_input(self, client, org_token, arguments):
        response = call_org_tool(client, org_token, "create_space", arguments)

        result = response.json()["result"]
        assert result["isError"] is True
        assert result["content"][0]["text"].startswith("Invalid arguments:")

    def test_create_space_reports_tree_validation_error(self, client, org_token, event):
        parent = SpaceFactory(event=event, parent=None, name="Scheduled room")
        AgendaItemFactory(space=parent)

        response = call_org_tool(
            client,
            org_token,
            "create_space",
            {"name": "Nested room", "parent_id": parent.pk},
        )

        result = response.json()["result"]
        assert result["isError"] is True
        assert result["content"][0]["text"] == (
            "A space holding a scheduled session cannot contain other spaces."
        )

    def test_create_track_rejects_foreign_space_without_side_effects(
        self, client, org_token, sphere, event
    ):
        sibling = EventFactory(sphere=sphere)
        foreign_space = SpaceFactory(event=sibling)

        response = call_org_tool(
            client,
            org_token,
            "create_track",
            {"name": "Foreign room track", "space_ids": [foreign_space.pk]},
        )

        result = response.json()["result"]
        assert result["isError"] is True
        assert result["content"][0]["text"] == "Resource not found"
        assert not Track.objects.filter(event=event, name="Foreign room track").exists()

    def test_create_space_rejects_foreign_parent(
        self, client, org_token, sphere, event
    ):
        sibling = EventFactory(sphere=sphere)
        foreign_parent = SpaceFactory(event=sibling, name="Sibling room")

        response = call_org_tool(
            client,
            org_token,
            "create_space",
            {"name": "Nested", "parent_id": foreign_parent.pk},
        )

        result = response.json()["result"]
        assert result["isError"] is True
        assert result["content"][0]["text"] == "Resource not found"

    def test_create_time_slot_rejects_reversed_range(self, client, org_token, event):
        start = event.start_time + timedelta(hours=4)
        end = event.start_time + timedelta(hours=2)

        response = call_org_tool(
            client,
            org_token,
            "create_time_slot",
            {"start_time": start.isoformat(), "end_time": end.isoformat()},
        )

        result = response.json()["result"]
        assert result["isError"] is True
        assert result["content"][0]["text"] == "start_not_before_end"
