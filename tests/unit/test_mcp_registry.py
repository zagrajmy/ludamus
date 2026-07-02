import pytest
from pydantic import BaseModel

from ludamus.gates.mcp.registry import Tool, ToolCall, ToolError, ToolRegistry
from ludamus.gates.mcp.tools import build_registry
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


def test_build_registry_has_no_organizer_tools_yet():
    registry = build_registry(ToolScope.ORGANIZER)

    assert registry.describe() == []


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
