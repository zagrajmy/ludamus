import logging
from unittest.mock import MagicMock

import pytest

from ludamus.gates.mcp.protocol import handle_message
from ludamus.gates.mcp.tools import build_registry
from ludamus.pacts.mcp import ActorContext, ToolScope


def _tools_call_record(caplog):
    return next(
        record for record in caplog.records if record.msg.startswith("mcp.tools_call")
    )


class TestMcpToolCallAudit:
    @pytest.fixture
    def actor(self):
        return ActorContext(user_id=7, scope=ToolScope.ORGANIZER, sphere_id=3)

    @pytest.fixture
    def registry(self):
        return build_registry(ToolScope.ORGANIZER)

    def test_audit_redacts_arguments_for_unknown_tool(self, caplog, registry, actor):
        caplog.set_level(logging.INFO)

        handle_message(
            registry=registry,
            services=MagicMock(),
            actor=actor,
            message={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "no_such_tool",
                    "arguments": {"display_name": "Alice", "description": "secret"},
                },
            },
        )

        assert _tools_call_record(caplog).args[-1] == "[redacted]"

    def test_audit_redacts_arguments_for_invalid_params(self, caplog, registry, actor):
        caplog.set_level(logging.INFO)

        handle_message(
            registry=registry,
            services=MagicMock(),
            actor=actor,
            message={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": 123, "arguments": {"display_name": "Alice"}},
            },
        )

        assert _tools_call_record(caplog).args[-1] == "[redacted]"

    def test_audit_sanitizes_known_tool_with_invalid_arguments(
        self, caplog, registry, actor
    ):
        caplog.set_level(logging.INFO)

        handle_message(
            registry=registry,
            services=MagicMock(),
            actor=actor,
            message={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "create_session",
                    "arguments": {
                        "display_name": "Alice",
                        "description": "secret plot",
                        "title": "Workshop",
                    },
                },
            },
        )

        assert _tools_call_record(caplog).args[-1] == {
            "display_name": "[redacted]",
            "description": "[redacted]",
            "title": "Workshop",
        }
