from __future__ import annotations

import json
from typing import cast
from urllib.parse import urlparse

import requests


class McpError(RuntimeError):
    pass


def failure_detail(response_text: str) -> str:
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return response_text
    # A batch tool answers with {"summary": ..., "results": [...]}; anything
    # else -- a scalar, null, a plain list -- is a message, not a report.
    if not isinstance(payload, dict):
        return response_text
    results = payload.get("results")
    if not isinstance(results, list):
        return response_text
    failures = [
        row for row in results if isinstance(row, dict) and row.get("status") != "ok"
    ]
    if not failures:
        return response_text
    return f"{payload.get('summary')}; failures: {failures}"


def _checked_endpoint(endpoint: str) -> str:
    # Every call carries the bearer token, so plaintext is only ever safe on
    # the loopback interface.
    parsed = urlparse(endpoint)
    if parsed.scheme == "https":
        return endpoint
    if parsed.scheme != "http":
        message = f"Unsupported endpoint scheme {parsed.scheme!r}: use https"
        raise McpError(message)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        message = f"Refusing to send the token over http to {parsed.hostname!r}"
        raise McpError(message)
    return endpoint


class McpClient:
    def __init__(self, *, endpoint: str, token: str) -> None:
        self.endpoint = _checked_endpoint(endpoint)
        self.token = token
        self.request_id = 0

    def call_object(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        result = self.call(name, arguments)
        if not isinstance(result, dict):
            message = f"{name}: expected an object, got {type(result).__name__}"
            raise McpError(message)
        return result

    def call_list(
        self, name: str, arguments: dict[str, object]
    ) -> list[dict[str, object]]:
        result = self.call(name, arguments)
        if not isinstance(result, list) or not all(
            isinstance(row, dict) for row in result
        ):
            message = f"{name}: expected a list of objects"
            raise McpError(message)
        return cast("list[dict[str, object]]", result)

    def call(self, name: str, arguments: dict[str, object]) -> object:
        self.request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        try:
            response = requests.post(
                self.endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=60,
            )
        except requests.RequestException as error:
            message = f"{name}: {error}"
            raise McpError(message) from error
        if not response.ok:
            message = f"{name}: HTTP {response.status_code}: {response.text}"
            raise McpError(message)
        body = cast("dict[str, object]", response.json())
        if "error" in body:
            message = f"{name}: {body['error']}"
            raise McpError(message)
        result = cast("dict[str, object]", body.get("result", {}))
        content = result.get("content")
        first = content[0] if isinstance(content, list) and content else None
        response_text = str(first.get("text", "")) if isinstance(first, dict) else ""
        if result.get("isError"):
            message = f"{name}: {failure_detail(response_text)}"
            raise McpError(message)
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            return response_text
