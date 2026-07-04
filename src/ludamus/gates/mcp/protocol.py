"""Stateless MCP JSON-RPC message handling.

Implements the request/response subset of the MCP Streamable HTTP transport:
each POSTed JSON-RPC message maps to exactly one JSON response (or none for
notifications). No sessions, no SSE — every call is authenticated and
self-contained, which is all a tool-only server needs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from ludamus.gates.mcp.registry import (
    InvalidArgumentsError,
    ToolError,
    UnknownToolError,
)
from ludamus.pacts import NotFoundError

if TYPE_CHECKING:
    from ludamus.gates.mcp.registry import ToolRegistry
    from ludamus.pacts.mcp import ActorContext
    from ludamus.pacts.services import ServicesProtocol

PROTOCOL_VERSION = "2025-06-18"
_KNOWN_PROTOCOL_VERSIONS = ("2025-03-26", PROTOCOL_VERSION, "2025-11-25")
SERVER_VERSION = "0.1.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

logger = logging.getLogger(__name__)

type JsonDict = dict[str, object]
type ToolOutcome = Literal[
    "ok", "error", "invalid-arguments", "invalid-params", "unknown-tool"
]


def error_response(*, message_id: object, code: int, message: str) -> JsonDict:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": message},
    }


def _result(message_id: object, result: JsonDict) -> JsonDict:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _initialize_result(params: JsonDict) -> JsonDict:
    requested = params.get("protocolVersion")
    version = requested if requested in _KNOWN_PROTOCOL_VERSIONS else PROTOCOL_VERSION
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {
            "name": "ludamus",
            "title": "Zagrajmy",
            "version": SERVER_VERSION,
        },
    }


def _text_result(*, message_id: object, text: str, is_error: bool) -> JsonDict:
    return _result(
        message_id, {"content": [{"type": "text", "text": text}], "isError": is_error}
    )


def _call_tool(
    *,
    registry: ToolRegistry,
    services: ServicesProtocol,
    actor: ActorContext,
    message_id: object,
    params: JsonDict,
) -> JsonDict:
    name = params.get("name")
    if (arguments := params.get("arguments")) is None:
        arguments = {}
    outcome: ToolOutcome
    if not isinstance(name, str) or not isinstance(arguments, dict):
        outcome, text = "invalid-params", "Invalid tool call params"
    else:
        outcome, text = _run_tool(
            registry=registry,
            services=services,
            actor=actor,
            name=name,
            arguments=arguments,
        )
    # Audit trail (#480): one line per tools/call.
    # %r on client-controlled values: repr escapes newlines, so a crafted
    # tool name cannot inject fake audit lines.
    logger.info(
        "mcp.tools_call user_id=%s scope=%s sphere_id=%s tool=%r outcome=%s "
        "arguments=%r",
        actor.user_id,
        actor.scope,
        actor.sphere_id,
        name,
        outcome,
        arguments,
    )
    if outcome in {"invalid-params", "unknown-tool"}:
        return error_response(message_id=message_id, code=INVALID_PARAMS, message=text)
    return _text_result(message_id=message_id, text=text, is_error=outcome != "ok")


def _run_tool(
    *,
    registry: ToolRegistry,
    services: ServicesProtocol,
    actor: ActorContext,
    name: str,
    arguments: dict[str, object],
) -> tuple[ToolOutcome, str]:
    try:
        text = registry.call(
            services=services, actor=actor, name=name, arguments=arguments
        )
    except UnknownToolError:
        return "unknown-tool", f"Unknown tool: {name}"
    except InvalidArgumentsError as error:
        return "invalid-arguments", str(error)
    except NotFoundError:
        return "error", "Resource not found"
    except ToolError as error:
        return "error", str(error)
    return "ok", text


def handle_message(
    *,
    registry: ToolRegistry,
    services: ServicesProtocol,
    actor: ActorContext,
    message: JsonDict,
) -> JsonDict | None:
    method = message.get("method")
    message_id = message.get("id")
    if not isinstance(method, str):
        return error_response(
            message_id=message_id, code=INVALID_REQUEST, message="Invalid request"
        )
    if message_id is None:
        # A notification (e.g. notifications/initialized): accept, no response.
        return None

    params = message.get("params")
    if not isinstance(params, dict):
        params = {}

    match method:
        case "initialize":
            return _result(message_id, _initialize_result(params))
        case "ping":
            return _result(message_id, {})
        case "tools/list":
            return _result(message_id, {"tools": registry.describe()})
        case "tools/call":
            return _call_tool(
                registry=registry,
                services=services,
                actor=actor,
                message_id=message_id,
                params=params,
            )
        case _:
            return error_response(
                message_id=message_id,
                code=METHOD_NOT_FOUND,
                message=f"Method not found: {method}",
            )
