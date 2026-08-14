import pytest
from pydantic import BaseModel

from ludamus.gates.mcp.registry import Tool, ToolCall, ToolError, ToolRegistry
from ludamus.gates.mcp.tools import build_registry, sanitize_audit_arguments
from ludamus.pacts.mcp import ActorContext, ToolScope

MAINTAINER_TOOL_NAMES = [
    "list_spheres",
    "get_sphere",
    "list_events",
    "get_event",
    "list_announcements",
    "create_announcement",
    "update_announcement",
    "delete_announcement",
]


class _EchoInput(BaseModel):
    suffix: str


class _EchoActorTool(Tool[_EchoInput]):
    name = "echo_actor"
    description = "Echo the acting user id."
    scope = ToolScope.ORGANIZER
    input_model = _EchoInput

    @staticmethod
    def handle(call: ToolCall[_EchoInput]) -> str:
        return f"{call.actor.user_id}:{call.actor.scope}:{call.data.suffix}"


class _FakeServices:
    pass


def test_build_registry_loads_only_maintainer_tools():
    registry = build_registry(ToolScope.MAINTAINER)

    assert [tool["name"] for tool in registry.describe()] == MAINTAINER_TOOL_NAMES


ORGANIZER_TOOL_NAMES = [
    "get_sphere",
    "list_events",
    "get_event",
    "create_event",
    "list_spaces",
    "list_time_slots",
    "list_tracks",
    "list_sessions",
    "list_facilitators",
    "create_space",
    "create_time_slot",
    "create_track",
    "create_proposal_category",
    "find_or_create_facilitator",
    "create_session",
    "assign_session",
    "list_announcements",
    "create_announcement",
    "update_announcement",
    "delete_announcement",
]


def test_build_registry_loads_only_organizer_tools():
    registry = build_registry(ToolScope.ORGANIZER)

    assert [tool["name"] for tool in registry.describe()] == ORGANIZER_TOOL_NAMES


def test_run_threads_actor_context_into_handle():
    registry = ToolRegistry([_EchoActorTool()])
    actor = ActorContext(user_id=7, scope=ToolScope.ORGANIZER, sphere_id=3)

    result = registry.call(
        services=_FakeServices(),
        actor=actor,
        name="echo_actor",
        arguments={"suffix": "ok"},
    )

    assert result == "7:organizer:ok"


def test_run_rejects_invalid_arguments_before_handle():
    registry = ToolRegistry([_EchoActorTool()])
    actor = ActorContext(user_id=7, scope=ToolScope.ORGANIZER)

    with pytest.raises(ToolError, match="Invalid arguments"):
        registry.call(
            services=_FakeServices(), actor=actor, name="echo_actor", arguments={}
        )


def test_invalid_arguments_message_hides_input_values():
    registry = ToolRegistry([_EchoActorTool()])
    actor = ActorContext(user_id=7, scope=ToolScope.ORGANIZER)

    with pytest.raises(ToolError) as excinfo:
        registry.call(
            services=_FakeServices(),
            actor=actor,
            name="echo_actor",
            arguments={"suffix": 424242},
        )

    message = str(excinfo.value)
    assert message == "Invalid arguments: suffix: Input should be a valid string"
    assert "424242" not in message


def test_sanitize_audit_arguments_redacts_sensitive_fields():
    arguments = {
        "event_id": 1,
        "display_name": "Alice",
        "description": "Secret plot",
        "title": "Workshop",
    }

    redacted = sanitize_audit_arguments("create_session", arguments)

    assert redacted == {
        "event_id": 1,
        "display_name": "[redacted]",
        "description": "[redacted]",
        "title": "Workshop",
    }


def test_create_event_rejects_naive_datetime():
    registry = build_registry(ToolScope.ORGANIZER)
    actor = ActorContext(user_id=1, scope=ToolScope.ORGANIZER, sphere_id=1)

    with pytest.raises(ToolError, match="timezone-aware"):
        registry.call(
            services=_FakeServices(),
            actor=actor,
            name="create_event",
            arguments={
                "name": "Bad tz",
                "slug": "bad-tz",
                "start_time": "2026-09-25T10:00:00",
                "end_time": "2026-09-27T18:00:00+02:00",
            },
        )


def test_create_event_rejects_blank_slug():
    registry = build_registry(ToolScope.ORGANIZER)
    actor = ActorContext(user_id=1, scope=ToolScope.ORGANIZER, sphere_id=1)

    with pytest.raises(ToolError, match="non-empty URL slug"):
        registry.call(
            services=_FakeServices(),
            actor=actor,
            name="create_event",
            arguments={
                "name": "Bad slug",
                "slug": "   ",
                "start_time": "2026-09-25T10:00:00+02:00",
                "end_time": "2026-09-27T18:00:00+02:00",
            },
        )
