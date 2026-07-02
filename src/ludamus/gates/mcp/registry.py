"""MCP tool registry.

Tools are thin adapters over `ServicesProtocol`: validate a pydantic input,
call a service, return the resulting DTO(s) as JSON text. The registry is the
single source of truth for what an MCP client can see and call; transports
(the HTTP endpoint today) stay dumb.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ludamus.pacts.services import ServicesProtocol


class ToolError(Exception):
    """Tool failure reported to the MCP client as an `isError` result."""


class UnknownToolError(Exception):
    pass


class ToolProtocol(Protocol):
    name: str
    description: str

    def input_schema(self) -> dict[str, object]: ...
    def run(self, services: ServicesProtocol, arguments: dict[str, object]) -> str: ...


class Tool[InputT: BaseModel](ToolProtocol, ABC):
    input_model: type[InputT]

    def input_schema(self) -> dict[str, object]:
        return self.input_model.model_json_schema()

    def run(self, services: ServicesProtocol, arguments: dict[str, object]) -> str:
        try:
            data = self.input_model.model_validate(arguments)
        except ValidationError as error:
            message = f"Invalid arguments: {error}"
            raise ToolError(message) from error
        return self.handle(services, data)

    @staticmethod
    @abstractmethod
    def handle(services: ServicesProtocol, data: InputT) -> str: ...


class ToolRegistry:
    def __init__(self, tools: Sequence[ToolProtocol]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def describe(self) -> list[dict[str, object]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema(),
            }
            for tool in self._tools.values()
        ]

    def call(
        self, *, services: ServicesProtocol, name: str, arguments: dict[str, object]
    ) -> str:
        if name not in self._tools:
            raise UnknownToolError(name)
        return self._tools[name].run(services, arguments)
