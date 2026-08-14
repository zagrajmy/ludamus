from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from ludamus.gates.mcp.protocol import sanitize_audit_arguments
from ludamus.gates.mcp.registry import Tool, ToolCall, ToolError, ToolRegistry
from ludamus.gates.mcp.tools import build_registry
from ludamus.pacts.mcp import ActorContext, ToolScope
from ludamus.pacts.timetable import PlacementRejectedError

MAINTAINER_TOOL_NAMES = [
    "list_spheres",
    "get_sphere",
    "list_events",
    "get_event",
    "create_event",
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
    "list_spaces",
    "list_time_slots",
    "list_tracks",
    "list_proposal_categories",
    "list_sessions",
    "list_facilitators",
    "create_space",
    "create_time_slot",
    "create_track",
    "create_proposal_category",
    "find_or_create_facilitator",
    "create_session",
    "create_sessions",
    "assign_session",
    "assign_sessions",
    "list_announcements",
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


def test_sanitize_batch_audit_arguments_keeps_only_correlation_keys():
    arguments = {
        "sessions": [
            {
                "source_row_id": "row-1",
                "display_name": "Alice",
                "description": "Secret plot",
                "title": "Workshop",
            },
            {
                "source_row_id": "row-2",
                "display_name": "Bob",
                "description": "Another secret",
                "title": "Panel",
            },
        ]
    }

    redacted = sanitize_audit_arguments("create_sessions", arguments)

    assert redacted == {"session_count": 2, "source_row_ids": ["row-1", "row-2"]}


def test_create_event_rejects_naive_datetime():
    registry = build_registry(ToolScope.MAINTAINER)
    actor = ActorContext(user_id=1, scope=ToolScope.MAINTAINER)

    with pytest.raises(ToolError, match="timezone-aware"):
        registry.call(
            services=_FakeServices(),
            actor=actor,
            name="create_event",
            arguments={
                "sphere_id": 1,
                "name": "Bad tz",
                "slug": "bad-tz",
                "start_time": "2026-09-25T10:00:00",
                "end_time": "2026-09-27T18:00:00+02:00",
            },
        )


def test_create_event_rejects_blank_name():
    registry = build_registry(ToolScope.MAINTAINER)
    actor = ActorContext(user_id=1, scope=ToolScope.MAINTAINER)

    with pytest.raises(ToolError, match="Invalid arguments"):
        registry.call(
            services=_FakeServices(),
            actor=actor,
            name="create_event",
            arguments={
                "sphere_id": 1,
                "name": "   ",
                "slug": "blank-name",
                "start_time": "2026-09-25T10:00:00+02:00",
                "end_time": "2026-09-27T18:00:00+02:00",
            },
        )


def test_create_event_rejects_blank_slug():
    registry = build_registry(ToolScope.MAINTAINER)
    actor = ActorContext(user_id=1, scope=ToolScope.MAINTAINER)

    with pytest.raises(ToolError, match="letters, numbers"):
        registry.call(
            services=_FakeServices(),
            actor=actor,
            name="create_event",
            arguments={
                "sphere_id": 1,
                "name": "Bad slug",
                "slug": "   ",
                "start_time": "2026-09-25T10:00:00+02:00",
                "end_time": "2026-09-27T18:00:00+02:00",
            },
        )


def test_create_event_rejects_a_slug_that_cannot_match_its_url():
    registry = build_registry(ToolScope.MAINTAINER)
    actor = ActorContext(user_id=1, scope=ToolScope.MAINTAINER)

    with pytest.raises(ToolError, match="letters, numbers"):
        registry.call(
            services=_FakeServices(),
            actor=actor,
            name="create_event",
            arguments={
                "sphere_id": 1,
                "name": "Bad slug",
                "slug": "not a slug",
                "start_time": "2026-09-25T10:00:00+02:00",
                "end_time": "2026-09-27T18:00:00+02:00",
            },
        )


def _organizer_actor():
    return ActorContext(user_id=7, scope=ToolScope.ORGANIZER, sphere_id=3, event_id=11)


def _session_input(source_row_id: str) -> dict[str, str | int]:
    return {"source_row_id": source_row_id, "title": "Session", "category_id": 5}


@pytest.mark.parametrize("count", (0, 251))
def test_create_sessions_enforces_batch_bounds(count):
    registry = build_registry(ToolScope.ORGANIZER)
    sessions = [_session_input(f"row-{index}") for index in range(count)]

    with pytest.raises(ToolError, match="Invalid arguments"):
        registry.call(
            services=_FakeServices(),
            actor=_organizer_actor(),
            name="create_sessions",
            arguments={"sessions": sessions},
        )


def test_create_sessions_rejects_duplicate_source_ids():
    registry = build_registry(ToolScope.ORGANIZER)

    with pytest.raises(ToolError, match="must be unique within a batch"):
        registry.call(
            services=_FakeServices(),
            actor=_organizer_actor(),
            name="create_sessions",
            arguments={"sessions": [_session_input("same"), _session_input("same")]},
        )


@pytest.mark.parametrize("count", (0, 251))
def test_assign_sessions_enforces_batch_bounds(count):
    registry = build_registry(ToolScope.ORGANIZER)
    assignment = {
        "session_id": 1,
        "space_id": 2,
        "start_time": "2026-09-25T10:00:00+02:00",
        "end_time": "2026-09-25T11:00:00+02:00",
    }

    with pytest.raises(ToolError, match="Invalid arguments"):
        registry.call(
            services=_FakeServices(),
            actor=_organizer_actor(),
            name="assign_sessions",
            arguments={
                "assignments": [{**assignment, "session_id": i} for i in range(count)]
            },
        )


def test_assign_sessions_rejects_duplicate_session_ids():
    registry = build_registry(ToolScope.ORGANIZER)
    assignment = {
        "session_id": 1,
        "space_id": 2,
        "start_time": "2026-09-25T10:00:00+02:00",
        "end_time": "2026-09-25T11:00:00+02:00",
    }

    with pytest.raises(ToolError, match="must be unique within a batch"):
        registry.call(
            services=_FakeServices(),
            actor=_organizer_actor(),
            name="assign_sessions",
            arguments={"assignments": [assignment, assignment]},
        )


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    (
        ("create_space", {"name": "   "}),
        ("create_track", {"name": "   "}),
        ("create_proposal_category", {"name": "   "}),
        ("find_or_create_facilitator", {"display_name": "   "}),
        (
            "create_session",
            {"source_row_id": "row-1", "title": "   ", "category_id": 5},
        ),
    ),
)
def test_programme_tools_reject_blank_names(tool_name, arguments):
    registry = build_registry(ToolScope.ORGANIZER)

    with pytest.raises(ToolError, match="Invalid arguments"):
        registry.call(
            services=_FakeServices(),
            actor=_organizer_actor(),
            name=tool_name,
            arguments=arguments,
        )


def test_create_session_rejects_malformed_duration():
    registry = build_registry(ToolScope.ORGANIZER)

    with pytest.raises(ToolError, match="Invalid arguments"):
        registry.call(
            services=_FakeServices(),
            actor=_organizer_actor(),
            name="create_session",
            arguments={
                "source_row_id": "row-1",
                "title": "Session",
                "category_id": 5,
                "duration": "whenever",
            },
        )


def test_create_session_rejects_blank_idempotency_key():
    registry = build_registry(ToolScope.ORGANIZER)
    actor = ActorContext(user_id=7, scope=ToolScope.ORGANIZER, sphere_id=3, event_id=11)

    with pytest.raises(ToolError, match="source_row_id must be non-empty"):
        registry.call(
            services=_FakeServices(),
            actor=actor,
            name="create_session",
            arguments={"source_row_id": "   ", "title": "Bad key", "category_id": 5},
        )


def _assign_session_call(*, side_effect: Exception) -> None:
    services = MagicMock()
    services.events.require_in_sphere.return_value.pk = 11
    services.timetable.assign_session.side_effect = side_effect
    actor = ActorContext(user_id=7, scope=ToolScope.ORGANIZER, sphere_id=3, event_id=11)
    build_registry(ToolScope.ORGANIZER).call(
        services=services,
        actor=actor,
        name="assign_session",
        arguments={
            "session_id": 13,
            "space_id": 17,
            "start_time": datetime(2025, 9, 19, 16, 0, tzinfo=UTC),
            "end_time": datetime(2025, 9, 19, 17, 0, tzinfo=UTC),
        },
    )


def test_assign_session_converts_placement_rejection_to_tool_error():
    with pytest.raises(ToolError, match="placement rejected"):
        _assign_session_call(side_effect=PlacementRejectedError("placement rejected"))


def test_assign_session_does_not_hide_unrelated_value_error():
    with pytest.raises(ValueError, match="unexpected failure"):
        _assign_session_call(side_effect=ValueError("unexpected failure"))
