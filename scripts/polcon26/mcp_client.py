from __future__ import annotations

import json
from typing import cast

import httpx


class McpError(RuntimeError):
    pass


def failure_detail(response_text: str) -> str:
    try:
        payload = cast("dict[str, object]", json.loads(response_text))
    except json.JSONDecodeError:
        return response_text
    results = cast("list[dict[str, object]]", payload.get("results", []))
    if not (failures := [row for row in results if row.get("status") != "ok"]):
        return response_text
    return f"{payload.get('summary')}; failures: {failures}"


class McpClient:
    def __init__(self, *, endpoint: str, token: str) -> None:
        self.endpoint = endpoint
        self.token = token
        self.request_id = 0

    def call(self, name: str, arguments: dict[str, object]) -> object:
        self.request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        try:
            response = httpx.post(
                self.endpoint,
                json=payload,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=60,
            )
            response.raise_for_status()
            body = cast("dict[str, object]", response.json())
        except httpx.HTTPStatusError as error:
            message = (
                f"{name}: HTTP {error.response.status_code}: {error.response.text}"
            )
            raise McpError(message) from error
        except httpx.RequestError as error:
            message = f"{name}: {error}"
            raise McpError(message) from error
        if "error" in body:
            message = f"{name}: {body['error']}"
            raise McpError(message)
        result = cast("dict[str, object]", body.get("result", {}))
        content = cast("list[dict[str, object]]", result.get("content", []))
        response_text = str(content[0].get("text", "")) if content else ""
        if result.get("isError"):
            message = f"{name}: {failure_detail(response_text)}"
            raise McpError(message)
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            return response_text
