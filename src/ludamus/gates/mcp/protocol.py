"""Stateless MCP JSON-RPC message handling.

Implements the request/response subset of the MCP Streamable HTTP transport:
each POSTed JSON-RPC message maps to exactly one JSON response (or none for
notifications). No sessions, no SSE — every call is authenticated and
self-contained, which is all a tool-only server needs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ludamus.gates.mcp.registry import ToolError, UnknownToolError
from ludamus.pacts import NotFoundError

if TYPE_CHECKING:
    from ludamus.gates.mcp.registry import ToolRegistry
    from ludamus.pacts.services import ServicesProtocol

PROTOCOL_VERSION = "2025-06-18"
_KNOWN_PROTOCOL_VERSIONS = ("2025-03-26", PROTOCOL_VERSION, "2025-11-25")
SERVER_VERSION = "0.1.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

type JsonDict = dict[str, object]


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
    message_id: object,
    params: JsonDict,
) -> JsonDict:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(name, str) or not isinstance(arguments, dict):
        return error_response(
            message_id=message_id,
            code=INVALID_PARAMS,
            message="Invalid tool call params",
        )
    try:
        text = registry.call(services=services, name=name, arguments=arguments)
    except UnknownToolError:
        return error_response(
            message_id=message_id, code=INVALID_PARAMS, message=f"Unknown tool: {name}"
        )
    except NotFoundError:
        return _text_result(
            message_id=message_id, text="Resource not found", is_error=True
        )
    except ToolError as error:
        return _text_result(message_id=message_id, text=str(error), is_error=True)
    return _text_result(message_id=message_id, text=text, is_error=False)


def handle_message(
    *, registry: ToolRegistry, services: ServicesProtocol, message: JsonDict
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
                message_id=message_id,
                params=params,
            )
        case _:
            return error_response(
                message_id=message_id,
                code=METHOD_NOT_FOUND,
                message=f"Method not found: {method}",
            )
